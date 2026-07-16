"""Test cho tool ``search`` chạy trên Tavily.

Ta truyền một client giả nên các test này không đụng mạng và không cần API key.
Client giả ghi lại cách nó bị gọi, cho phép ta kiểm tra rằng ta forward đúng tham số.
"""

from __future__ import annotations

import pytest

from deep_research_agent.tools.search import search


class FakeTavilyClient:
    """Đóng thế cho ``AsyncTavilyClient``, trả về kết quả dựng sẵn."""

    def __init__(self, results: list[dict]) -> None:
        self._results = results
        self.calls: list[tuple[str, dict]] = []

    async def search(self, query: str, **kwargs) -> dict:
        self.calls.append((query, kwargs))
        return {"results": self._results}


async def test_search_maps_provider_fields_to_schema() -> None:
    fake = FakeTavilyClient(
        [{"title": "Quant 101", "url": "https://ex.com/q", "content": "snip", "score": 0.87}]
    )

    results = await search("quantization", client=fake)

    assert len(results) == 1
    r = results[0]
    assert r.title == "Quant 101"
    assert r.url == "https://ex.com/q"
    assert r.snippet == "snip"  # "content" của Tavily ánh xạ sang "snippet" của ta
    assert r.score == 0.87


async def test_search_forwards_max_results() -> None:
    fake = FakeTavilyClient([])

    await search("anything", max_results=3, client=fake)

    _query, kwargs = fake.calls[0]
    assert kwargs["max_results"] == 3


async def test_search_empty_provider_response_returns_empty_list() -> None:
    fake = FakeTavilyClient([])

    assert await search("nothing found", client=fake) == []


async def test_search_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Vô hiệu hóa việc nạp .env và xóa key để nhánh dựng client hỏng một cách đoán trước
    # được, bất kể máy dev có file .env thật hay không.
    monkeypatch.setattr("deep_research_agent.tools.search.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        await search("no client, no key")
