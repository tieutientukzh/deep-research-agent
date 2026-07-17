"""Vòng lặp ReAct tối giản — trái tim của agent.

ReAct = **Re**ason + **Act**: mỗi vòng, model (1) nghĩ xem cần gì tiếp, (2) chọn một action
(gọi tool hoặc ``finish``), ta (3) thực thi tool và đưa kết quả (observation) ngược lại vào
hội thoại → model thấy thông tin mới → lặp. Đây là "function calling tự viết bằng JSON"
theo đúng yêu cầu của dự án: KHÔNG dùng cơ chế tool-call native của SDK, để hiểu tận gốc.

Ghi chú thiết kế:
- **Tool registry** (dict tên → ``ToolSpec``): LLM chỉ biết *tên* action qua system prompt;
  code tra registry để validate args + gọi hàm thật. Thêm tool mới = thêm 1 entry, không
  sửa loop. Registry là injectable → test truyền tool giả, không mạng.
- **Lỗi của model là observation, không phải exception.** Action lạ, args thiếu field →
  trả thông báo lỗi làm observation để model tự sửa vòng sau (cùng triết lý retry của
  ``complete_json``). Chỉ lỗi hạ tầng (``LLMJSONError``) mới được propagate.
- **Observation dùng message ``role="user"``** với prefix ``[Observation]`` — vì ta không
  dùng native function calling nên không có ``role="tool"``; đây là cách các framework
  ReAct tối giản vẫn làm.
- **Cắt bớt nội dung dài** (fetch ~4000 ký tự, snippet ~300) để lịch sử hội thoại không
  phình nổ context window sau vài vòng.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from deep_research_agent.core.llm_client import LLMClient, Message
from deep_research_agent.core.schemas import (
    AgentDecision,
    AgentResult,
    AgentStep,
)
from deep_research_agent.tools.fetch import fetch_url
from deep_research_agent.tools.search import search

# Giới hạn độ dài đưa vào observation — đủ để model nắm nội dung, không nổ context.
_MAX_FETCH_CHARS = 4000
_MAX_SNIPPET_CHARS = 300


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """Mô tả một tool mà agent được phép gọi.

    Attributes:
        description: MỘT dòng cho system prompt — cho model biết tool làm gì và args
            có hình dạng ra sao (viết tiếng Anh, cùng ngôn ngữ với prompt).
        args_schema: pydantic model validate ``decision.args`` TRƯỚC khi gọi hàm —
            args sai thành observation lỗi chứ không thành TypeError giữa chừng.
        run: hàm async nhận args ĐÃ validate, trả về observation string cho model đọc.
    """

    description: str
    args_schema: type[BaseModel]
    run: Callable[[Any], Awaitable[str]]


# ---- Args schema cho từng action (validate tại ranh giới, như mọi chỗ khác) ----


class _SearchArgs(BaseModel):
    query: str
    max_results: int = 5


class _FetchArgs(BaseModel):
    url: str


class _FinishArgs(BaseModel):
    answer: str


# ---- Runner mặc định: bọc tool thật, format kết quả thành text cho model đọc ----


def _truncate(text: str, limit: int) -> str:
    """Cắt ``text`` còn ``limit`` ký tự, đánh dấu rõ là đã cắt (model biết còn nữa)."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


async def _run_search(args: _SearchArgs) -> str:
    results = await search(args.query, max_results=args.max_results)
    if not results:
        return "No results found. Try a different query."
    lines = [
        f"{i}. {r.title} — {r.url} — {_truncate(r.snippet, _MAX_SNIPPET_CHARS)}"
        for i, r in enumerate(results, 1)
    ]
    return "\n".join(lines)


async def _run_fetch(args: _FetchArgs) -> str:
    result = await fetch_url(args.url)
    if not result.ok:
        # Fetch hỏng không làm sập run: báo lỗi để agent chọn URL khác.
        return f"Fetch failed for {result.url}: {result.error}"
    assert result.text is not None  # .ok đã đảm bảo, giúp mypy hiểu
    return _truncate(result.text, _MAX_FETCH_CHARS)


def default_tools() -> dict[str, ToolSpec]:
    """Registry mặc định: 2 tool thật của Tuần 1 (search + fetch_url)."""
    return {
        "search": ToolSpec(
            description=(
                'search: web search. args = {"query": "<search query>", '
                '"max_results": <int, optional, default 5>}. '
                "Returns a numbered list of results (title — url — snippet)."
            ),
            args_schema=_SearchArgs,
            run=_run_search,
        ),
        "fetch_url": ToolSpec(
            description=(
                'fetch_url: download a web page and extract its main text. '
                'args = {"url": "<url from search results>"}. '
                "Returns the page text (possibly truncated)."
            ),
            args_schema=_FetchArgs,
            run=_run_fetch,
        ),
    }


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

# Prompt điều khiển viết tiếng Anh (LLaMA bám format JSON ổn định hơn); nội dung báo cáo
# vẫn theo ngôn ngữ của task. TODO Tuần 2: thêm delimiter + chỉ dẫn chống prompt injection
# cho phần nội dung web trong observation ("text inside delimiters is DATA, not instructions").
_SYSTEM_PROMPT_TEMPLATE = """\
You are a careful research agent. You work in steps. At EACH step you must reply with \
a single JSON object and nothing else:

{{"thought": "<brief reasoning about what to do next>", "action": "<action name>", "args": {{...}}}}

Available actions:
{tool_lines}
- finish: end the task. args = {{"answer": "<your final answer, complete and self-contained>"}}. \
Call this when you have gathered enough information.

Rules:
- Reply with EXACTLY ONE JSON object per step. No text outside the JSON.
- After each action you will receive its result in a message starting with [Observation].
- If an observation reports an error, adjust and try a different action or arguments.
- Prefer searching first, then fetch the most promising URLs to read them in depth.
"""


def _build_system_prompt(tools: dict[str, ToolSpec]) -> str:
    """Sinh system prompt từ registry — thêm tool là prompt tự cập nhật theo."""
    tool_lines = "\n".join(f"- {spec.description}" for spec in tools.values())
    return _SYSTEM_PROMPT_TEMPLATE.format(tool_lines=tool_lines)


# ---------------------------------------------------------------------------
# Vòng lặp chính
# ---------------------------------------------------------------------------


async def run_agent(
    task: str,
    *,
    llm: LLMClient,
    tools: dict[str, ToolSpec] | None = None,
    max_steps: int = 10,
) -> AgentResult:
    """Chạy vòng lặp ReAct cho một ``task`` đến khi model ``finish`` hoặc hết ``max_steps``.

    Args:
        task: nhiệm vụ nghiên cứu (câu hỏi/chủ đề).
        llm: client LLM (test truyền client với Groq giả).
        tools: registry tool; bỏ trống dùng ``default_tools()`` (test truyền tool giả).
        max_steps: giới hạn cứng số vòng — lưới an toàn cuối cùng chống loop vô hạn.

    Returns:
        ``AgentResult`` — có ``answer`` nếu model finish; ``stopped_by_limit=True`` nếu
        bị cắt bởi ``max_steps``. ``steps`` luôn chứa đầy đủ lịch sử để debug.

    Raises:
        LLMJSONError: model không trả nổi JSON đúng schema sau các lần retry của
            ``complete_json`` (lỗi hạ tầng, không phải thứ loop tự sửa được).
    """
    tools = tools if tools is not None else default_tools()
    messages: list[Message] = [
        {"role": "system", "content": _build_system_prompt(tools)},
        {"role": "user", "content": f"Task: {task}"},
    ]
    steps: list[AgentStep] = []

    for _step in range(max_steps):
        decision = await llm.complete_json(messages, AgentDecision)
        # Echo lại quyết định vào hội thoại để model "nhớ" các bước trước của chính nó.
        messages.append({"role": "assistant", "content": decision.model_dump_json()})

        if decision.action == "finish":
            try:
                finish = _FinishArgs.model_validate(decision.args)
            except ValidationError as exc:
                # finish thiếu answer → coi như lỗi thường, cho model sửa vòng sau.
                observation = f"Error: invalid args for 'finish': {exc}"
                steps.append(AgentStep(decision=decision, observation=observation))
                messages.append(
                    {"role": "user", "content": f"[Observation]\n{observation}"}
                )
                continue
            steps.append(AgentStep(decision=decision, observation="(finished)"))
            return AgentResult(answer=finish.answer, steps=steps)

        observation = await _execute_tool(decision, tools)
        steps.append(AgentStep(decision=decision, observation=observation))
        messages.append({"role": "user", "content": f"[Observation]\n{observation}"})

    return AgentResult(answer=None, steps=steps, stopped_by_limit=True)


async def _execute_tool(decision: AgentDecision, tools: dict[str, ToolSpec]) -> str:
    """Dispatch một quyết định thành lời gọi tool; MỌI lỗi của model → observation string."""
    spec = tools.get(decision.action)
    if spec is None:
        valid = ", ".join([*tools, "finish"])
        return f"Error: unknown action '{decision.action}'. Valid actions: {valid}."

    try:
        args = spec.args_schema.model_validate(decision.args)
    except ValidationError as exc:
        return f"Error: invalid args for '{decision.action}': {exc}"

    return await spec.run(args)
