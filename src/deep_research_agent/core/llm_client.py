"""Wrapper quanh Groq API — "cái miệng" để agent nói chuyện với LLM.

Vì sao cần một lớp bọc thay vì gọi thẳng Groq ở khắp nơi?
- Gom cấu hình (API key, chọn model nhanh/mạnh) về MỘT chỗ.
- Cung cấp *structured output*: ép model trả JSON, parse an toàn, và **tự sửa** khi JSON hỏng.
  Nhờ vậy Planner/Researcher/Writer chỉ việc xin "một object đúng schema", khỏi lo parse.
- Cách ly phần còn lại của codebase khỏi chi tiết SDK Groq (mai này đổi provider dễ hơn).

Ghi chú thiết kế:
- **Async** cho nhất quán với tool layer (search/fetch).
- **Dependency Injection**: nhận ``client`` dựng sẵn để test truyền client giả, không gọi mạng.
- **Retry chỉ cho JSON hỏng** (Tuần 1); backoff cho lỗi mạng/rate-limit để Tuần 2.
"""

from __future__ import annotations

import json
import os
from typing import TypeVar

from dotenv import load_dotenv
from groq import AsyncGroq
from pydantic import BaseModel, ValidationError

# TypeVar "gắn" kiểu schema caller truyền vào với kiểu trả về: đưa schema là lớp X (con của
# BaseModel) thì complete_json trả về đúng một object X — IDE/mypy hiểu được kiểu, không phải "Any".
T = TypeVar("T", bound=BaseModel)

# Một message trong hội thoại: {"role": "system"|"user"|"assistant", "content": "..."}.
Message = dict[str, str]

# Model mặc định nếu .env không khai báo (khớp .env.example).
_DEFAULT_MODEL_FAST = "llama-3.1-8b-instant"
_DEFAULT_MODEL_STRONG = "llama-3.3-70b-versatile"


class LLMJSONError(RuntimeError):
    """Model vẫn không trả JSON hợp lệ/đúng schema sau khi đã hết số lần thử lại."""


class LLMClient:
    """Client gọi Groq với 2 chế độ: text thường (``complete``) và JSON có schema.

    JSON có schema dùng ``complete_json`` — ép model trả object đúng một pydantic schema.
    """

    def __init__(
        self,
        *,
        client: AsyncGroq | None = None,
        model_fast: str | None = None,
        model_strong: str | None = None,
    ) -> None:
        """Dựng client.

        Args:
            client: ``AsyncGroq`` dựng sẵn (test truyền vào). Nếu bỏ trống sẽ tự dựng từ
                ``GROQ_API_KEY`` — thiếu key thì raise ngay (lỗi cấu hình cần sửa liền).
            model_fast: tên model rẻ/nhanh (planning, sinh search query). Mặc định lấy từ
                ``GROQ_MODEL_FAST`` trong .env.
            model_strong: tên model mạnh (viết báo cáo). Mặc định ``GROQ_MODEL_STRONG``.
        """
        load_dotenv()
        self.model_fast = model_fast or os.getenv("GROQ_MODEL_FAST") or _DEFAULT_MODEL_FAST
        self.model_strong = (
            model_strong or os.getenv("GROQ_MODEL_STRONG") or _DEFAULT_MODEL_STRONG
        )

        if client is not None:
            self._client = client
        else:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "GROQ_API_KEY chưa được đặt. Copy .env.example thành .env và điền key."
                )
            self._client = AsyncGroq(api_key=api_key)

    async def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.3,
    ) -> str:
        """Sinh văn bản thường (không ép JSON). Mặc định dùng model MẠNH (hợp cho viết)."""
        return await self._create(
            messages, model=model or self.model_strong, temperature=temperature
        )

    async def complete_json(
        self,
        messages: list[Message],
        schema: type[T],
        *,
        model: str | None = None,
        max_retries: int = 2,
    ) -> T:
        """Xin model trả về một object đúng ``schema`` (pydantic).

        Cơ chế: bật JSON mode của Groq (đảm bảo cú pháp JSON hợp lệ) → ``json.loads`` →
        validate vào ``schema``. Nếu parse/validate hỏng, **nhét câu trả lời hỏng + mô tả lỗi
        ngược lại cho model** rồi thử lại, tối đa ``max_retries`` lần. Hết lượt → raise.

        Mặc định dùng model NHANH (structured task như planning không cần model mạnh).
        """
        model = model or self.model_fast
        # Copy để không làm thay đổi list messages của caller (tránh tác dụng phụ khó lường).
        convo: list[Message] = list(messages)
        last_error: Exception | None = None

        # range(max_retries + 1): 1 lần thử đầu + max_retries lần sửa lỗi.
        for _attempt in range(max_retries + 1):
            raw = await self._create(convo, model=model, temperature=0.0, json_mode=True)
            try:
                data = json.loads(raw)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                # Đưa output hỏng + lỗi vào hội thoại để model "sửa bài" ở vòng sau.
                convo = convo + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "Câu trả lời trước KHÔNG phải JSON hợp lệ đúng schema. "
                            f"Lỗi: {exc}. Hãy trả về LẠI chỉ JSON hợp lệ, không thêm chữ nào khác."
                        ),
                    },
                ]

        raise LLMJSONError(
            f"Không lấy được JSON đúng schema sau {max_retries + 1} lần thử. "
            f"Lỗi cuối: {last_error}"
        )

    async def _create(
        self,
        messages: list[Message],
        *,
        model: str,
        temperature: float,
        json_mode: bool = False,
    ) -> str:
        """Gọi chat completion của Groq và trả về phần text của câu trả lời.

        Gom mọi lời gọi API về một chỗ để hai method public dùng chung.
        """
        # response_format bật "json_object" → Groq đảm bảo message trả về là JSON hợp lệ về cú pháp.
        response_format = {"type": "json_object"} if json_mode else None
        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            response_format=response_format,  # type: ignore[arg-type]
        )
        content = response.choices[0].message.content
        return content or ""
