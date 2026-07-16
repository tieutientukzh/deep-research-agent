"""Tool tìm kiếm web: biến một chuỗi truy vấn thành danh sách kết quả xếp hạng qua Tavily.

Ghi chú thiết kế:
- **Async** để sau này vòng lặp nghiên cứu có thể chạy nhiều lượt search đồng thời.
- **Dependency injection:** caller có thể truyền sẵn một ``AsyncTavilyClient``; nếu không,
  ta tự dựng từ ``TAVILY_API_KEY``. Test truyền client giả nên không đụng mạng và không cần
  API key.
- Trả về ``SearchResult`` của riêng ta, không phải dict thô của Tavily, để phần còn lại của
  codebase được cách ly khỏi nhà cung cấp search (fallback như Serper để Tuần 2).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from tavily import AsyncTavilyClient

from deep_research_agent.core.schemas import SearchResult


def _build_client() -> AsyncTavilyClient:
    """Dựng client Tavily thật từ biến môi trường, lỗi ngay nếu thiếu key."""
    load_dotenv()  # idempotent: nạp TAVILY_API_KEY từ .env vào os.environ
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY chưa được đặt. Copy .env.example thành .env và điền key."
        )
    return AsyncTavilyClient(api_key=api_key)


async def search(
    query: str,
    *,
    max_results: int = 5,
    client: AsyncTavilyClient | None = None,
) -> list[SearchResult]:
    """Tìm kiếm web và trả về tối đa ``max_results`` kết quả, liên quan nhất trước.

    Args:
        query: Chuỗi truy vấn tìm kiếm.
        max_results: Giới hạn số kết quả trả về.
        client: Client Tavily dựng sẵn (test truyền vào); nếu bỏ trống sẽ tự dựng từ
            ``TAVILY_API_KEY``.

    Returns:
        Danh sách ``SearchResult`` (có thể rỗng nếu nhà cung cấp không tìm thấy gì).
    """
    client = client or _build_client()
    response = await client.search(query, max_results=max_results)

    results: list[SearchResult] = []
    for item in response.get("results", []):
        results.append(
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                score=item.get("score"),
            )
        )
    return results
