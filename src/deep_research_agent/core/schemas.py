"""Các schema pydantic dùng chung, truyền qua lại giữa tool và agent.

Gom về một chỗ để mọi tầng (tools, agents, storage) thống nhất đúng hình dạng dữ liệu —
và pydantic validate ngay tại ranh giới, nên một response API dị dạng sẽ báo lỗi ngay ở
đây thay vì âm thầm làm hỏng báo cáo ở bước sau.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class AgentDecision(BaseModel):
    """Quyết định của LLM ở MỖI vòng ReAct: nghĩ gì (thought) và làm gì tiếp (action + args).

    Đây chính là "function calling tự viết": thay vì dùng cơ chế tool-call native của SDK,
    ta ép model trả về đúng object này qua JSON mode rồi tự dispatch. ``finish`` là một
    action giả — cách chuẩn để agent tự tuyên bố "đã đủ thông tin, đây là câu trả lời"
    thay vì lặp vô hạn.
    """

    thought: str
    # Là ``str`` thay vì ``Literal[...]`` có chủ đích: tên tool hợp lệ do tool REGISTRY quyết
    # định lúc chạy (registry là injectable). Nếu khóa cứng bằng Literal, một action lạ sẽ
    # fail validation ngay trong complete_json và cuối cùng CRASH — trong khi ta muốn nó chỉ
    # tạo ra một observation lỗi để model tự sửa ở vòng sau.
    action: str
    # Tham số cho action, hình dạng tùy action: {"query": ...} / {"url": ...} / {"answer": ...}.
    # Để dict thô ở đây và validate bằng schema con TRONG loop — nhờ vậy args sai chỉ tạo ra
    # một observation lỗi cho model tự sửa, không làm hỏng việc parse cả quyết định.
    args: dict[str, Any] = Field(default_factory=dict)


class AgentStep(BaseModel):
    """Một bước ReAct đã thực thi xong: quyết định của model + kết quả quan sát được.

    Lưu lại toàn bộ các bước để debug ("vì sao agent chọn URL này?") và sau này ghi vào
    SQLite làm dữ liệu evaluation.
    """

    decision: AgentDecision
    observation: str


class AgentResult(BaseModel):
    """Kết quả cuối của một lần chạy agent loop.

    ``answer`` là ``None`` khi loop bị cắt bởi ``max_steps`` trước khi model kịp ``finish``
    — phân biệt rõ "trả lời xong" với "hết kiên nhẫn" qua ``stopped_by_limit``.
    """

    answer: str | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    stopped_by_limit: bool = False
