"""Sổ cái nguồn dùng chung cho chế độ nghiên cứu deep — ``SourceRegistry``.

Vì sao cần nó? Trong pipeline thô (T1) *code* fetch sẵn các nguồn nên biết rõ URL nào ứng
với citation ``[n]``. Nhưng khi chuyển sang **Researcher ReAct loop**, chính *model* mới là
bên đi search/fetch bên trong loop; kết quả trả ra ngoài chỉ là một đoạn ``answer`` text tự
do — mất dấu "đã đọc URL nào". Nếu chỉ đưa các answer cho Writer thì báo cáo sẽ KHÔNG còn
citation tra được nguồn (thụt lùi so với T1).

``SourceRegistry`` vá đúng chỗ đó: mỗi lần Researcher fetch **thành công** một URL, wrapper
tool lặng lẽ ``add()`` nguồn vào sổ này và nhận lại một id ``[n]`` toàn cục. Điểm mấu chốt
về mặt thiết kế:
- **Agent KHÔNG biết registry tồn tại** — việc ghi sổ là side-effect trong wrapper của tool
  ``fetch_url``, không tốn "sức chú ý" của model, không thêm action nào vào prompt.
- **id toàn cục, dedupe theo URL**: hai sub-question fetch cùng một trang → cùng một ``[n]``,
  nên báo cáo không bị trùng nguồn và citation vẫn nhất quán xuyên các sub-question.
"""

from __future__ import annotations

from deep_research_agent.core.schemas import Source

# Mỗi nguồn cắt còn ~6000 ký tự — cùng lý do với pipeline thô: đủ chi tiết cho báo cáo mà
# không nổ context của model 70B khi gộp nhiều nguồn vào một lời gọi Writer.
_MAX_SOURCE_CHARS = 6000


def _truncate(text: str, limit: int) -> str:
    """Cắt ``text`` còn ``limit`` ký tự, đánh dấu rõ là đã cắt (Writer biết còn nữa)."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


class SourceRegistry:
    """Bộ đăng ký nguồn: cấp id ``[n]`` toàn cục, dedupe theo URL.

    Dùng chung cho cả một lần chạy deep pipeline (mọi sub-question chia sẻ một registry),
    nên citation ``[n]`` là duy nhất và ổn định trên toàn báo cáo.
    """

    def __init__(self) -> None:
        # Giữ theo thứ tự thêm vào (id 1, 2, 3...) + index theo URL để dedupe O(1).
        self._sources: list[Source] = []
        self._by_url: dict[str, Source] = {}

    def add(self, url: str, title: str, text: str) -> Source:
        """Thêm một nguồn đã fetch thành công; trả về ``Source`` (kèm id ``[n]``).

        Nếu ``url`` đã có trong sổ, KHÔNG thêm mới mà trả lại ``Source`` cũ (giữ nguyên id) —
        nhờ vậy cùng một trang được nhiều sub-question đọc vẫn chỉ mang một citation.
        """
        existing = self._by_url.get(url)
        if existing is not None:
            return existing

        source = Source(
            id=len(self._sources) + 1,
            title=title or url,
            url=url,
            text=_truncate(text, _MAX_SOURCE_CHARS),
        )
        self._sources.append(source)
        self._by_url[url] = source
        return source

    @property
    def sources(self) -> list[Source]:
        """Danh sách nguồn theo thứ tự id (bản sao nông để caller không sửa nội bộ)."""
        return list(self._sources)

    def __len__(self) -> int:
        return len(self._sources)
