"""Test cho pipeline thô end-to-end (``pipeline.py``).

Fake ở BA tầng, không test nào chạm mạng:
- LLM: Groq giả trả nội dung theo hàng đợi (mirror ``test_llm_client.py``) — cho phép
  soi cả prompt đã gửi đi (``calls``) để kiểm nội dung nguồn có vào prompt writer không.
- ``search_fn``/``fetch_fn``: fake async function truyền qua DI — kiểm flow chọn/skip URL.
- ``on_progress``: gom vào list thay vì in stderr — test im lặng, lại kiểm được cảnh báo.
"""

from __future__ import annotations

from deep_research_agent.core.llm_client import LLMClient
from deep_research_agent.core.schemas import FetchResult, SearchResult
from deep_research_agent.pipeline import _MAX_SOURCE_CHARS, run_pipeline

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


def _make_llm(reports: list[str]) -> tuple[LLMClient, FakeGroq]:
    fake = FakeGroq(reports)
    llm = LLMClient(client=fake, model_fast="fast-model", model_strong="strong-model")
    return llm, fake


# ---- Fake tools: search trả danh sách dựng sẵn, fetch hỏng theo danh sách URL ----


def _results(n: int) -> list[SearchResult]:
    return [
        SearchResult(
            title=f"Title {i}", url=f"https://example.com/{i}", snippet=f"snippet {i}"
        )
        for i in range(1, n + 1)
    ]


def _make_search_fn(results: list[SearchResult]):
    async def fake_search(query: str, *, max_results: int = 5) -> list[SearchResult]:
        return results

    return fake_search


def _make_fetch_fn(broken_urls: set[str] | None = None, text_by_url: dict | None = None):
    """Fetch giả: URL trong ``broken_urls`` trả lỗi, còn lại trả text (tùy biến được)."""
    broken = broken_urls or set()
    texts = text_by_url or {}
    calls: list[str] = []

    async def fake_fetch(url: str) -> FetchResult:
        calls.append(url)
        if url in broken:
            return FetchResult(url=url, error="dead link")
        return FetchResult(url=url, status_code=200, text=texts.get(url, f"content of {url}"))

    fake_fetch.calls = calls  # type: ignore[attr-defined]
    return fake_fetch


# ---- Tests ----


async def test_happy_path_builds_report_from_fetched_sources():
    llm, fake = _make_llm(["# Report\ncontent [1]"])
    fetch_fn = _make_fetch_fn()
    progress: list[str] = []

    result = await run_pipeline(
        "test topic",
        llm=llm,
        search_fn=_make_search_fn(_results(6)),
        fetch_fn=fetch_fn,
        on_progress=progress.append,
    )

    assert result.report == "# Report\ncontent [1]"
    assert result.error is None
    # Dừng đúng ở max_sources=5 dù search trả 6 kết quả; id gán tuần tự 1..5.
    assert [s.id for s in result.sources] == [1, 2, 3, 4, 5]
    assert fetch_fn.calls == [f"https://example.com/{i}" for i in range(1, 6)]

    # Prompt writer phải chứa topic + nguồn đánh số [n] kèm url và toàn văn đã fetch.
    (call,) = fake.chat.completions.calls
    user_content = call["messages"][1]["content"]
    assert "Topic: test topic" in user_content
    assert "[1] Title 1 (https://example.com/1)" in user_content
    assert "content of https://example.com/5" in user_content
    # Bước viết dùng model strong (complete mặc định).
    assert call["model"] == "strong-model"


async def test_broken_urls_are_skipped_and_replaced():
    llm, _ = _make_llm(["report"])
    broken = {"https://example.com/1", "https://example.com/3"}
    fetch_fn = _make_fetch_fn(broken_urls=broken)

    result = await run_pipeline(
        "topic",
        llm=llm,
        max_sources=3,
        search_fn=_make_search_fn(_results(6)),
        fetch_fn=fetch_fn,
        on_progress=lambda _msg: None,
    )

    # URL hỏng bị bỏ qua, lấy URL kế tiếp theo rank cho đủ 3 nguồn sống.
    assert [s.url for s in result.sources] == [
        "https://example.com/2",
        "https://example.com/4",
        "https://example.com/5",
    ]
    assert result.skipped_urls == sorted(broken)
    assert result.report == "report"


async def test_no_fetchable_source_returns_error_without_llm_call():
    llm, fake = _make_llm(["should never be used"])
    all_broken = {f"https://example.com/{i}" for i in range(1, 4)}

    result = await run_pipeline(
        "topic",
        llm=llm,
        search_fn=_make_search_fn(_results(3)),
        fetch_fn=_make_fetch_fn(broken_urls=all_broken),
        on_progress=lambda _msg: None,
    )

    assert result.report is None
    assert result.error is not None
    assert "no source" in result.error
    # Không có nguồn thì KHÔNG được đốt tiền gọi LLM.
    assert fake.chat.completions.calls == []


async def test_empty_search_returns_error():
    llm, fake = _make_llm(["unused"])

    result = await run_pipeline(
        "topic",
        llm=llm,
        search_fn=_make_search_fn([]),
        fetch_fn=_make_fetch_fn(),
        on_progress=lambda _msg: None,
    )

    assert result.report is None
    assert result.error == "search returned no results"
    assert fake.chat.completions.calls == []


async def test_fewer_than_min_sources_still_writes_report_with_warning():
    llm, _ = _make_llm(["short report"])
    progress: list[str] = []

    result = await run_pipeline(
        "topic",
        llm=llm,
        min_sources=3,
        search_fn=_make_search_fn(_results(1)),
        fetch_fn=_make_fetch_fn(),
        on_progress=progress.append,
    )

    # 1 nguồn < min_sources=3: vẫn ra báo cáo (thà mỏng còn hơn không) nhưng có cảnh báo.
    assert result.report == "short report"
    assert len(result.sources) == 1
    assert any("only 1/3 sources" in msg for msg in progress)


async def test_duplicate_urls_are_fetched_once():
    llm, _ = _make_llm(["report"])
    duplicated = [_results(1)[0], _results(1)[0], _results(2)[1]]
    fetch_fn = _make_fetch_fn()

    result = await run_pipeline(
        "topic",
        llm=llm,
        search_fn=_make_search_fn(duplicated),
        fetch_fn=fetch_fn,
        on_progress=lambda _msg: None,
    )

    assert fetch_fn.calls == ["https://example.com/1", "https://example.com/2"]
    assert [s.url for s in result.sources] == [
        "https://example.com/1",
        "https://example.com/2",
    ]


async def test_long_source_text_is_truncated_in_prompt():
    llm, fake = _make_llm(["report"])
    long_text = "x" * (_MAX_SOURCE_CHARS + 500)
    fetch_fn = _make_fetch_fn(text_by_url={"https://example.com/1": long_text})

    result = await run_pipeline(
        "topic",
        llm=llm,
        search_fn=_make_search_fn(_results(1)),
        fetch_fn=fetch_fn,
        on_progress=lambda _msg: None,
    )

    source_text = result.sources[0].text
    assert source_text.endswith("...[truncated]")
    assert len(source_text) <= _MAX_SOURCE_CHARS + len("\n...[truncated]")
    (call,) = fake.chat.completions.calls
    assert "...[truncated]" in call["messages"][1]["content"]
