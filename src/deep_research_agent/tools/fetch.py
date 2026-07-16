"""Tool fetch trang: tải một URL và trích ra phần nội dung chính.

Ghi chú thiết kế:
- **Async** (httpx.AsyncClient) để sau này có thể fetch nhiều trang đồng thời.
- **Không ném exception với các lỗi lường trước** (link chết, timeout, chặn bot, trang rỗng):
  mọi nhánh đều trả về ``FetchResult`` có ``error``. Vòng lặp nghiên cứu coi fetch hỏng là
  "bỏ qua nguồn này", chứ không phải "làm sập run".
- **Nội dung web là DỮ LIỆU, không phải chỉ dẫn.** Ở đây ta chỉ *trích* text; việc bọc an
  toàn trước khi đưa vào prompt LLM (chống prompt injection) làm ở tầng agent.
- ``trafilatura.extract`` là lời gọi đồng bộ, nặng CPU — chạy inline cho một trang là ổn;
  chưa đẩy sang thread (tối ưu sớm không cần thiết cho Tuần 1).
"""

from __future__ import annotations

import httpx
import trafilatura

from deep_research_agent.core.schemas import FetchResult

# User-Agent giả trình duyệt thật để giảm bị chặn bot đơn giản ở nhiều site.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


async def fetch_url(
    url: str,
    *,
    timeout: float = 10.0,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    """Fetch ``url`` và trả về phần text chính đã trích (hoặc lỗi đã ghi lại).

    Args:
        url: Trang cần tải.
        timeout: Thời gian chờ mỗi request (giây).
        client: Client httpx dựng sẵn (test truyền vào); nếu bỏ trống sẽ tự tạo và tự đóng.

    Returns:
        Một ``FetchResult``; kiểm tra ``.ok`` trước khi tin dùng ``.text``.
    """
    if client is not None:
        return await _fetch_with(client, url, timeout)

    async with httpx.AsyncClient(
        follow_redirects=True, headers=_HEADERS, timeout=timeout
    ) as owned_client:
        return await _fetch_with(owned_client, url, timeout)


async def _fetch_with(
    client: httpx.AsyncClient, url: str, timeout: float
) -> FetchResult:
    """Thực hiện GET + trích nội dung bằng một client đã mở sẵn."""
    try:
        response = await client.get(url, timeout=timeout, headers=_HEADERS)
    except httpx.RequestError as exc:
        # Lỗi tầng mạng: DNS, từ chối kết nối, timeout, lỗi TLS...
        return FetchResult(url=url, error=f"request failed: {exc!r}")

    if response.status_code != httpx.codes.OK:
        return FetchResult(
            url=url,
            status_code=response.status_code,
            error=f"unexpected status {response.status_code}",
        )

    text = trafilatura.extract(response.text, url=url)
    if not text or not text.strip():
        return FetchResult(
            url=url,
            status_code=response.status_code,
            error="no main content extracted",
        )

    return FetchResult(url=url, status_code=response.status_code, text=text)
