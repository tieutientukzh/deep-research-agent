"""Các schema pydantic dùng chung, truyền qua lại giữa tool và agent.

Gom về một chỗ để mọi tầng (tools, agents, storage) thống nhất đúng hình dạng dữ liệu —
và pydantic validate ngay tại ranh giới, nên một response API dị dạng sẽ báo lỗi ngay ở
đây thay vì âm thầm làm hỏng báo cáo ở bước sau.
"""

from __future__ import annotations

from pydantic import BaseModel


class SearchResult(BaseModel):
    """Một kết quả trả về từ tool tìm kiếm web.

    ``snippet`` là đoạn tóm tắt ngắn mà search API trả về; toàn văn trang chỉ được lấy
    riêng bằng ``fetch_url`` cho những URL mà agent quyết định đọc.
    """

    title: str
    url: str
    snippet: str = ""
    score: float | None = None


class FetchResult(BaseModel):
    """Kết quả của việc fetch + trích xuất nội dung một URL.

    Một lần fetch có thể hỏng theo nhiều cách (link chết, bị chặn bot, trang rỗng). Thay vì
    ném exception, ``fetch_url`` luôn trả về một ``FetchResult`` và ghi lý do hỏng vào
    ``error`` — nhờ vậy vòng lặp nghiên cứu có thể bỏ qua nguồn lỗi và đi tiếp, thay vì làm
    sập cả run.
    """

    url: str
    text: str | None = None
    error: str | None = None
    status_code: int | None = None

    @property
    def ok(self) -> bool:
        """True khi đã trích được text dùng được và không gặp lỗi."""
        return self.error is None and bool(self.text and self.text.strip())
