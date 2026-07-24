"""Wrapper quanh LLM API — "cái miệng" để agent nói chuyện với LLM.

Vì sao cần một lớp bọc thay vì gọi thẳng SDK ở khắp nơi?
- Gom cấu hình (provider, API key, chọn model nhanh/mạnh) về MỘT chỗ.
- Cung cấp *structured output*: ép model trả JSON, parse an toàn, và **tự sửa** khi JSON hỏng.
  Nhờ vậy Planner/Researcher/Writer chỉ việc xin "một object đúng schema", khỏi lo parse.
- Cách ly phần còn lại của codebase khỏi chi tiết SDK (đổi provider chỉ sửa file này).

Ghi chú thiết kế:
- **MỘT SDK cho MỌI provider.** Cả Gemini lẫn Groq đều cung cấp endpoint
  *OpenAI-compatible* (cùng định dạng ``messages`` + ``response_format``), nên ta dùng
  ``AsyncOpenAI`` và chỉ đổi ``base_url`` + API key. Đổi provider = đổi 1 biến môi trường,
  KHÔNG phải viết client riêng cho từng hãng.
- **Vì sao cần nhiều provider?** Free tier mỗi hãng có trần khác nhau (Groq bị chặn ở
  100K token/ngày — quá ít cho deep mode; Gemini không có trần token/ngày). Giữ cả hai để
  còn đường lui khi một bên hết quota, và để so sánh trong bảng eval (Tuần 3).
- **Async** cho nhất quán với tool layer (search/fetch).
- **Dependency Injection**: nhận ``client`` dựng sẵn để test truyền client giả, không gọi mạng.
- **Retry chỉ cho JSON hỏng** (Tuần 1); backoff cho lỗi mạng/rate-limit để Tuần 2.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, TypeVar

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

# TypeVar "gắn" kiểu schema caller truyền vào với kiểu trả về: đưa schema là lớp X (con của
# BaseModel) thì complete_json trả về đúng một object X — IDE/mypy hiểu được kiểu, không phải "Any".
T = TypeVar("T", bound=BaseModel)

# Một message trong hội thoại: {"role": "system"|"user"|"assistant", "content": "..."}.
Message = dict[str, str]


@dataclass(frozen=True)
class ProviderConfig:
    """Mọi thứ khác nhau giữa các provider — gom lại để thêm hãng mới chỉ là thêm 1 entry.

    Attributes:
        base_url: endpoint OpenAI-compatible của hãng.
        api_key_env: tên biến môi trường chứa API key.
        env_prefix: tiền tố biến môi trường chọn model (``GEMINI_MODEL_FAST``...).
        default_fast: model rẻ/nhanh mặc định (planning, sinh search query).
        default_strong: model mạnh mặc định (quyết định trong ReAct loop, viết báo cáo).
    """

    base_url: str
    api_key_env: str
    env_prefix: str
    default_fast: str
    default_strong: str


# Bảng provider hỗ trợ sẵn. Lưu ý cả hai đều là endpoint OpenAI-compatible, KHÔNG phải
# API gốc của hãng — nhờ vậy dùng chung được một SDK.
PROVIDERS: dict[str, ProviderConfig] = {
    "gemini": ProviderConfig(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env="GEMINI_API_KEY",
        env_prefix="GEMINI",
        # Free tier của Google chỉ mở Flash/Flash-Lite (Pro nằm sau billing), nên "strong"
        # ở đây là Flash chứ không phải Pro.
        default_fast="gemini-flash-lite-latest",
        default_strong="gemini-flash-latest",
    ),
    "groq": ProviderConfig(
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        env_prefix="GROQ",
        default_fast="llama-3.1-8b-instant",
        default_strong="llama-3.3-70b-versatile",
    ),
}

# Provider mặc định khi .env không khai báo ``LLM_PROVIDER``.
_DEFAULT_PROVIDER = "gemini"


class LLMJSONError(RuntimeError):
    """Model vẫn không trả JSON hợp lệ/đúng schema sau khi đã hết số lần thử lại."""


class LLMClient:
    """Client gọi LLM với 2 chế độ: text thường (``complete``) và JSON có schema.

    JSON có schema dùng ``complete_json`` — ép model trả object đúng một pydantic schema.
    """

    def __init__(
        self,
        *,
        client: AsyncOpenAI | None = None,
        provider: str | None = None,
        model_fast: str | None = None,
        model_strong: str | None = None,
    ) -> None:
        """Dựng client.

        Args:
            client: ``AsyncOpenAI`` dựng sẵn (test truyền vào). Nếu bỏ trống sẽ tự dựng từ
                API key của provider — thiếu key thì raise ngay (lỗi cấu hình cần sửa liền).
            provider: ``"gemini"`` hoặc ``"groq"``. Mặc định lấy từ ``LLM_PROVIDER`` trong
                .env, không có thì dùng ``gemini``.
            model_fast: tên model rẻ/nhanh (planning, sinh search query). Mặc định lấy từ
                ``<PREFIX>_MODEL_FAST`` trong .env, rồi mới tới mặc định của provider.
            model_strong: tên model mạnh (viết báo cáo). Mặc định ``<PREFIX>_MODEL_STRONG``.

        Raises:
            ValueError: tên provider không nằm trong ``PROVIDERS``.
            RuntimeError: thiếu API key của provider đã chọn.
        """
        load_dotenv()
        self.provider = (provider or os.getenv("LLM_PROVIDER") or _DEFAULT_PROVIDER).lower()
        config = PROVIDERS.get(self.provider)
        if config is None:
            valid = ", ".join(sorted(PROVIDERS))
            raise ValueError(f"Provider '{self.provider}' không hỗ trợ. Chọn một trong: {valid}.")
        self.config = config

        # Thứ tự ưu tiên: tham số truyền thẳng > biến .env > mặc định của provider.
        self.model_fast = (
            model_fast or os.getenv(f"{config.env_prefix}_MODEL_FAST") or config.default_fast
        )
        self.model_strong = (
            model_strong or os.getenv(f"{config.env_prefix}_MODEL_STRONG") or config.default_strong
        )

        if client is not None:
            self._client = client
        else:
            api_key = os.getenv(config.api_key_env)
            if not api_key:
                raise RuntimeError(
                    f"{config.api_key_env} chưa được đặt (provider='{self.provider}'). "
                    "Copy .env.example thành .env và điền key."
                )
            self._client = AsyncOpenAI(api_key=api_key, base_url=config.base_url)

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

        Cơ chế: bật JSON mode của provider (đảm bảo cú pháp JSON hợp lệ) → ``json.loads`` →
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
        """Gọi chat completion của provider và trả về phần text của câu trả lời.

        Gom mọi lời gọi API về một chỗ để hai method public dùng chung.
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        # Chỉ gửi response_format khi thực sự cần JSON: một số endpoint OpenAI-compatible
        # từ chối `"response_format": null` nếu ta gửi None tường minh.
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        return content or ""
