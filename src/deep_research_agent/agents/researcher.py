"""Researcher — nghiên cứu MỘT sub-question bằng ReAct loop (bước [2] kiến trúc đích).

Mỗi sub-question chạy một vòng ``run_agent`` riêng: model tự sinh search query → chọn URL
đáng đọc → fetch → tự quyết đủ thông tin chưa → ``finish``. Đây là lúc tái sử dụng ReAct
loop đã viết ở Tuần 1.

Hai vấn đề của agentic loop được xử lý ở đây (xem NOTE.md để biết vì sao):
- **Model lười fetch** (finding smoke test T1): dùng **model strong (70B)** cho quyết định
  + **guard code** (``validate_finish``) từ chối ``finish`` khi chưa fetch được nguồn nào →
  ép model đọc nguồn thật, không trả lời từ mỗi snippet. Phòng thủ nhiều lớp: code > model
  > prompt.
- **Mất dấu citation**: wrapper của tool ``fetch_url`` lặng lẽ ghi mỗi nguồn fetch thành công
  vào ``SourceRegistry`` chung → báo cáo vẫn cite ``[n]`` tra được nguồn như T1. Agent không
  hề biết registry tồn tại (side-effect trong closure).

Ghi chú thiết kế:
- Tool registry được dựng RIÊNG cho mỗi lần chạy (closure bọc ``search_fn``/``fetch_fn`` +
  ``registry`` + ``on_progress``) → giữ DI cho test, không dùng biến toàn cục.
"""

from __future__ import annotations

from collections.abc import Callable

from deep_research_agent.core.agent_loop import (
    _MAX_FETCH_CHARS,
    _MAX_SNIPPET_CHARS,
    ToolSpec,
    _FetchArgs,
    _SearchArgs,
    _truncate,
    run_agent,
)
from deep_research_agent.core.llm_client import LLMClient
from deep_research_agent.core.schemas import FetchFn, SearchFn, SubQuestionResult
from deep_research_agent.core.sources import SourceRegistry
from deep_research_agent.tools.fetch import fetch_url
from deep_research_agent.tools.search import search


def _noop(_message: str) -> None:
    """Callback tiến độ mặc định: im lặng (pipeline sẽ truyền callback thật vào)."""


async def research_sub_question(
    question: str,
    *,
    llm: LLMClient,
    registry: SourceRegistry,
    search_fn: SearchFn = search,
    fetch_fn: FetchFn = fetch_url,
    max_steps: int = 8,
    on_progress: Callable[[str], None] = _noop,
) -> SubQuestionResult:
    """Chạy ReAct loop cho một sub-question; các nguồn fetch được ghi vào ``registry``.

    Args:
        question: câu hỏi con cần nghiên cứu.
        llm: client LLM; loop dùng model strong để ra quyết định (chọn URL/query tốt hơn).
        registry: sổ cái nguồn dùng chung — fetch thành công sẽ ``add()`` vào đây.
        search_fn / fetch_fn: tool thật mặc định; test truyền fake async function.
        max_steps: giới hạn cứng số vòng ReAct cho sub-question này.
        on_progress: callback tiến độ (mỗi lần search/fetch phát một dòng).

    Returns:
        ``SubQuestionResult`` — answer model tổng hợp, các id ``[n]`` toàn cục đã đóng góp,
        và cờ ``stopped_by_limit``.
    """
    # Tiêu đề trang lấy được từ kết quả search, để khi fetch thành công còn ghi vào registry.
    titles_by_url: dict[str, str] = {}
    # id các nguồn mà CHÍNH sub-question này đã fetch (giữ thứ tự, dedupe) — vừa để trả về,
    # vừa làm điều kiện cho guard "phải có ≥1 nguồn trước khi finish".
    collected_ids: list[int] = []

    async def run_search(args: _SearchArgs) -> str:
        on_progress(f"  search: {args.query}")
        results = await search_fn(args.query, max_results=args.max_results)
        if not results:
            return "No results found. Try a different query."
        lines = []
        for i, r in enumerate(results, 1):
            titles_by_url[r.url] = r.title
            snippet = _truncate(r.snippet, _MAX_SNIPPET_CHARS)
            lines.append(f"{i}. {r.title} — {r.url} — {snippet}")
        return "\n".join(lines)

    async def run_fetch(args: _FetchArgs) -> str:
        on_progress(f"  fetch: {args.url}")
        result = await fetch_fn(args.url)
        if not result.ok:
            # Fetch hỏng không làm sập run và KHÔNG ghi registry: báo lỗi để agent đổi URL.
            return f"Fetch failed for {result.url}: {result.error}"
        assert result.text is not None  # .ok đã đảm bảo, giúp mypy hiểu
        # Side-effect có chủ đích: ghi nguồn vào sổ chung, nhận id [n] toàn cục (dedupe URL).
        source = registry.add(
            args.url, titles_by_url.get(args.url, args.url), result.text
        )
        if source.id not in collected_ids:
            collected_ids.append(source.id)
        # Observation vẫn cắt ~4000 ký tự (registry giữ bản đầy đủ hơn cho Writer).
        return _truncate(result.text, _MAX_FETCH_CHARS)

    tools: dict[str, ToolSpec] = {
        "search": ToolSpec(
            description=(
                'search: web search. args = {"query": "<search query>", '
                '"max_results": <int, optional, default 5>}. '
                "Returns a numbered list of results (title — url — snippet)."
            ),
            args_schema=_SearchArgs,
            run=run_search,
        ),
        "fetch_url": ToolSpec(
            description=(
                "fetch_url: download a web page and extract its main text. "
                'args = {"url": "<url from search results>"}. '
                "Returns the page text (possibly truncated)."
            ),
            args_schema=_FetchArgs,
            run=run_fetch,
        ),
    }

    def validate_finish(_answer: str) -> str | None:
        """Guard: không cho finish khi chưa đọc nguồn nào — ép agent fetch trước."""
        if not collected_ids:
            return (
                "Error: you must fetch at least one source with fetch_url before "
                "finishing. Search, then fetch the most promising URL to read it."
            )
        return None

    on_progress(f"Researching: {question}")
    result = await run_agent(
        f"Research this question and answer it based on web sources: {question}",
        llm=llm,
        tools=tools,
        max_steps=max_steps,
        model=llm.model_strong,
        validate_finish=validate_finish,
    )

    return SubQuestionResult(
        question=question,
        answer=result.answer,
        source_ids=collected_ids,
        stopped_by_limit=result.stopped_by_limit,
    )
