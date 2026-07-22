"""Test cho Researcher (``agents/researcher.py``).

Fake ở ba tầng (LLM qua ``make_llm``, search/fetch qua DI, registry thật) — không mạng.
Trọng tâm: (1) fetch thành công ghi đúng nguồn vào registry; (2) fetch hỏng KHÔNG ghi;
(3) guard chặn finish khi chưa có nguồn; (4) dedupe URL xuyên sub-question; (5) dùng model
strong cho quyết định.
"""

from __future__ import annotations

from deep_research_agent.agents.researcher import research_sub_question
from deep_research_agent.core.schemas import FetchResult, SearchResult
from deep_research_agent.core.sources import SourceRegistry


def _make_search_fn(results: list[SearchResult]):
    async def fake_search(query: str, *, max_results: int = 5) -> list[SearchResult]:
        return results

    return fake_search


def _make_fetch_fn(broken: set[str] | None = None, text_by_url: dict | None = None):
    broken = broken or set()
    texts = text_by_url or {}

    async def fake_fetch(url: str) -> FetchResult:
        if url in broken:
            return FetchResult(url=url, error="dead link")
        return FetchResult(url=url, status_code=200, text=texts.get(url, f"text of {url}"))

    return fake_fetch


_RESULTS = [
    SearchResult(title="Page A", url="http://a", snippet="about a"),
    SearchResult(title="Page B", url="http://b", snippet="about b"),
]


async def test_successful_fetch_is_registered_and_uses_strong_model(
    make_llm, decision
) -> None:
    llm, fake = make_llm(
        [
            decision("search", {"query": "q"}),
            decision("fetch_url", {"url": "http://a"}),
            decision("finish", {"answer": "answer about A"}),
        ]
    )
    registry = SourceRegistry()

    result = await research_sub_question(
        "sub-question?",
        llm=llm,
        registry=registry,
        search_fn=_make_search_fn(_RESULTS),
        fetch_fn=_make_fetch_fn(),
    )

    assert result.answer == "answer about A"
    assert result.source_ids == [1]
    assert result.stopped_by_limit is False
    # Nguồn được ghi với id [1], title lấy từ kết quả search, text đầy đủ.
    (source,) = registry.sources
    assert (source.id, source.title, source.url) == (1, "Page A", "http://a")
    assert source.text == "text of http://a"
    # Loop dùng model STRONG cho quyết định.
    assert fake.chat.completions.calls[0]["model"] == "strong-model"


async def test_broken_fetch_is_not_registered(make_llm, decision) -> None:
    llm, _ = make_llm(
        [
            decision("search", {"query": "q"}),
            decision("fetch_url", {"url": "http://a"}),  # hỏng
            decision("fetch_url", {"url": "http://b"}),  # ok
            decision("finish", {"answer": "done"}),
        ]
    )
    registry = SourceRegistry()

    result = await research_sub_question(
        "q?",
        llm=llm,
        registry=registry,
        search_fn=_make_search_fn(_RESULTS),
        fetch_fn=_make_fetch_fn(broken={"http://a"}),
    )

    # Chỉ nguồn fetch thành công (http://b) vào registry.
    assert [s.url for s in registry.sources] == ["http://b"]
    assert result.source_ids == [1]


async def test_guard_blocks_finish_before_any_fetch(make_llm, decision) -> None:
    llm, _ = make_llm(
        [
            decision("finish", {"answer": "premature"}),  # bị guard chặn
            decision("search", {"query": "q"}),
            decision("fetch_url", {"url": "http://a"}),
            decision("finish", {"answer": "proper answer"}),
        ]
    )
    registry = SourceRegistry()

    result = await research_sub_question(
        "q?",
        llm=llm,
        registry=registry,
        search_fn=_make_search_fn(_RESULTS),
        fetch_fn=_make_fetch_fn(),
    )

    # finish sớm bị guard từ chối → model buộc phải search+fetch rồi mới finish lại được.
    # Bằng chứng: answer cuối là câu SAU khi đã fetch, không phải câu "premature", và nguồn
    # đã được ghi vào registry.
    assert result.answer == "proper answer"
    assert result.source_ids == [1]
    assert [s.url for s in registry.sources] == ["http://a"]


async def test_same_url_across_sub_questions_shares_one_id(make_llm, decision) -> None:
    registry = SourceRegistry()

    llm1, _ = make_llm(
        [
            decision("search", {"query": "q1"}),
            decision("fetch_url", {"url": "http://a"}),
            decision("finish", {"answer": "a1"}),
        ]
    )
    r1 = await research_sub_question(
        "q1?",
        llm=llm1,
        registry=registry,
        search_fn=_make_search_fn(_RESULTS),
        fetch_fn=_make_fetch_fn(),
    )

    llm2, _ = make_llm(
        [
            decision("search", {"query": "q2"}),
            decision("fetch_url", {"url": "http://a"}),  # cùng URL với q1
            decision("finish", {"answer": "a2"}),
        ]
    )
    r2 = await research_sub_question(
        "q2?",
        llm=llm2,
        registry=registry,
        search_fn=_make_search_fn(_RESULTS),
        fetch_fn=_make_fetch_fn(),
    )

    # Dedupe theo URL → chỉ một nguồn, cùng id [1] cho cả hai sub-question.
    assert len(registry) == 1
    assert r1.source_ids == [1]
    assert r2.source_ids == [1]
