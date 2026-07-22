"""Test cho vòng lặp ReAct (``core/agent_loop.py``).

Fake ở HAI tầng, không test nào chạm mạng:
- LLM: Groq giả trả nội dung theo hàng đợi (cùng pattern với ``test_llm_client.py``) —
  mỗi phần tử là một JSON ``AgentDecision``, mô phỏng chuỗi quyết định của model.
- Tools: registry giả với hàm async tự ghi lại lời gọi — kiểm được loop dispatch đúng
  tool, đúng args đã validate.

Riêng hai runner mặc định (``_run_search``/``_run_fetch`` — phần format + cắt bớt) được
test trực tiếp bằng cách monkeypatch tool thật bên dưới.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from deep_research_agent.core.agent_loop import ToolSpec, default_tools, run_agent
from deep_research_agent.core.llm_client import LLMClient
from deep_research_agent.core.schemas import FetchResult, SearchResult

# ---- Groq giả: trả lần lượt nội dung trong hàng đợi (mirror test_llm_client.py) ----


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self._queue = list(contents)
        self.calls: list[dict] = []

    async def create(self, **kwargs) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self._queue.pop(0))


class _FakeChat:
    def __init__(self, contents: list[str]) -> None:
        self.completions = _FakeCompletions(contents)


class FakeGroq:
    def __init__(self, contents: list[str]) -> None:
        self.chat = _FakeChat(contents)


def _make_llm(decisions: list[str]) -> tuple[LLMClient, FakeGroq]:
    fake = FakeGroq(decisions)
    llm = LLMClient(client=fake, model_fast="fast-model", model_strong="strong-model")
    return llm, fake


def _decision(action: str, args: dict | None = None, thought: str = "t") -> str:
    """JSON một ``AgentDecision`` — đúng thứ model thật sẽ trả về trong JSON mode."""
    return json.dumps({"thought": thought, "action": action, "args": args or {}})


# ---- Registry giả: tool tự ghi lại lời gọi, trả observation cố định ----


class _EchoSearchArgs(BaseModel):
    query: str
    max_results: int = 5


class _EchoFetchArgs(BaseModel):
    url: str


def _make_fake_tools() -> tuple[dict[str, ToolSpec], dict[str, list]]:
    calls: dict[str, list] = {"search": [], "fetch_url": []}

    async def fake_search(args: _EchoSearchArgs) -> str:
        calls["search"].append(args)
        return "1. Quantization guide — http://a — intro to LLM quantization"

    async def fake_fetch(args: _EchoFetchArgs) -> str:
        calls["fetch_url"].append(args)
        return "full text of page A"

    tools = {
        "search": ToolSpec(
            description='search: args = {"query": str}',
            args_schema=_EchoSearchArgs,
            run=fake_search,
        ),
        "fetch_url": ToolSpec(
            description='fetch_url: args = {"url": str}', args_schema=_EchoFetchArgs, run=fake_fetch
        ),
    }
    return tools, calls


# ---- Test vòng lặp ----


async def test_happy_path_search_fetch_finish() -> None:
    llm, fake = _make_llm(
        [
            _decision("search", {"query": "llm quantization"}),
            _decision("fetch_url", {"url": "http://a"}),
            _decision("finish", {"answer": "Báo cáo cuối."}),
        ]
    )
    tools, calls = _make_fake_tools()

    result = await run_agent("so sánh quantization", llm=llm, tools=tools)

    assert result.answer == "Báo cáo cuối."
    assert result.stopped_by_limit is False
    assert len(result.steps) == 3
    # Tool nhận đúng args đã validate qua schema.
    assert calls["search"][0].query == "llm quantization"
    assert calls["fetch_url"][0].url == "http://a"
    # Observation của search được đưa lại cho LLM ở lượt sau, dưới role user.
    second_call_messages = fake.chat.completions.calls[1]["messages"]
    last = second_call_messages[-1]
    assert last["role"] == "user"
    assert last["content"].startswith("[Observation]")
    assert "Quantization guide" in last["content"]


async def test_unknown_action_becomes_observation_then_recovers() -> None:
    # Vòng 1 model gọi action không tồn tại → không crash, nhận lỗi làm observation → sửa.
    llm, _fake = _make_llm(
        [
            _decision("searchh", {"query": "x"}),
            _decision("finish", {"answer": "ok"}),
        ]
    )
    tools, calls = _make_fake_tools()

    result = await run_agent("task", llm=llm, tools=tools)

    assert result.answer == "ok"
    assert "unknown action 'searchh'" in result.steps[0].observation
    assert calls["search"] == []  # tool thật không bị gọi nhầm


async def test_invalid_args_becomes_observation_then_recovers() -> None:
    # search thiếu field 'query' → ValidationError → observation lỗi, model sửa vòng sau.
    llm, _fake = _make_llm(
        [
            _decision("search", {}),
            _decision("finish", {"answer": "ok"}),
        ]
    )
    tools, calls = _make_fake_tools()

    result = await run_agent("task", llm=llm, tools=tools)

    assert result.answer == "ok"
    assert "invalid args for 'search'" in result.steps[0].observation
    assert calls["search"] == []


async def test_finish_without_answer_is_retried_in_loop() -> None:
    # finish thiếu 'answer' cũng chỉ là lỗi thường — loop tiếp tục, không kết thúc sớm.
    llm, _fake = _make_llm(
        [
            _decision("finish", {}),
            _decision("finish", {"answer": "ok"}),
        ]
    )
    tools, _calls = _make_fake_tools()

    result = await run_agent("task", llm=llm, tools=tools)

    assert result.answer == "ok"
    assert "invalid args for 'finish'" in result.steps[0].observation
    assert len(result.steps) == 2


async def test_stops_at_max_steps_without_finish() -> None:
    llm, _fake = _make_llm([_decision("search", {"query": "x"})] * 3)
    tools, calls = _make_fake_tools()

    result = await run_agent("task", llm=llm, tools=tools, max_steps=3)

    assert result.answer is None
    assert result.stopped_by_limit is True
    assert len(result.steps) == 3
    assert len(calls["search"]) == 3


async def test_model_param_is_passed_to_llm() -> None:
    llm, fake = _make_llm([_decision("finish", {"answer": "ok"})])
    tools, _calls = _make_fake_tools()

    await run_agent("task", llm=llm, tools=tools, model="strong-model")

    # Mỗi vòng quyết định phải gọi đúng model được chỉ định.
    assert fake.chat.completions.calls[0]["model"] == "strong-model"


async def test_validate_finish_rejection_continues_loop() -> None:
    # validate_finish từ chối lần đầu (answer chưa "đủ") → loop tiếp; lần sau chấp nhận.
    llm, _fake = _make_llm(
        [
            _decision("finish", {"answer": "too short"}),
            _decision("finish", {"answer": "a long enough answer"}),
        ]
    )
    tools, _calls = _make_fake_tools()

    def validate_finish(answer: str) -> str | None:
        return "Error: answer too short, keep researching." if len(answer) < 10 else None

    result = await run_agent(
        "task", llm=llm, tools=tools, validate_finish=validate_finish
    )

    assert result.answer == "a long enough answer"
    assert "too short" in result.steps[0].observation
    assert len(result.steps) == 2


# ---- Test runner mặc định (format + cắt bớt), monkeypatch tool thật bên dưới ----


async def test_default_search_runner_formats_results(monkeypatch) -> None:
    async def fake_search(query: str, *, max_results: int = 5) -> list[SearchResult]:
        return [
            SearchResult(title="A", url="http://a", snippet="sa"),
            SearchResult(title="B", url="http://b", snippet="sb"),
        ]

    monkeypatch.setattr("deep_research_agent.core.agent_loop.search", fake_search)
    spec = default_tools()["search"]

    obs = await spec.run(spec.args_schema.model_validate({"query": "q"}))

    assert obs.splitlines() == ["1. A — http://a — sa", "2. B — http://b — sb"]


async def test_default_fetch_runner_reports_error(monkeypatch) -> None:
    async def fake_fetch(url: str, **kwargs) -> FetchResult:
        return FetchResult(url=url, error="request failed: dead link")

    monkeypatch.setattr("deep_research_agent.core.agent_loop.fetch_url", fake_fetch)
    spec = default_tools()["fetch_url"]

    obs = await spec.run(spec.args_schema.model_validate({"url": "http://dead"}))

    assert "Fetch failed for http://dead" in obs
    assert "dead link" in obs


async def test_default_fetch_runner_truncates_long_text(monkeypatch) -> None:
    async def fake_fetch(url: str, **kwargs) -> FetchResult:
        return FetchResult(url=url, status_code=200, text="x" * 10_000)

    monkeypatch.setattr("deep_research_agent.core.agent_loop.fetch_url", fake_fetch)
    spec = default_tools()["fetch_url"]

    obs = await spec.run(spec.args_schema.model_validate({"url": "http://long"}))

    assert obs.endswith("...[truncated]")
    # 4000 ký tự nội dung + marker — không phình hơn.
    assert len(obs) < 4100
