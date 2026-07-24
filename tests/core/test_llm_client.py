"""Test cho ``LLMClient``.

Ta dựng một client GIẢ mô phỏng đúng hình dạng response thật
(``response.choices[0].message.content``) và trả nội dung theo HÀNG ĐỢI, nhờ đó mô phỏng được
tình huống "lần 1 model trả JSON hỏng, lần 2 trả đúng". Không có test nào gọi mạng thật.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from deep_research_agent.core.llm_client import LLMClient, LLMJSONError


# ---- Groq giả: các lớp nhỏ ghép lại cho giống cấu trúc response thật ----
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
        self._queue = list(contents)  # mỗi lần create() lấy 1 phần tử ra
        self.calls: list[dict] = []  # ghi lại tham số từng lần gọi để assert

    async def create(self, **kwargs) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self._queue.pop(0))


class _FakeChat:
    def __init__(self, contents: list[str]) -> None:
        self.completions = _FakeCompletions(contents)


class FakeLLM:
    """Đóng thế ``AsyncOpenAI``: trả lần lượt các nội dung trong ``contents``."""

    def __init__(self, contents: list[str]) -> None:
        self.chat = _FakeChat(contents)


def _make_client(contents: list[str]) -> tuple[LLMClient, FakeLLM]:
    fake = FakeLLM(contents)
    client = LLMClient(client=fake, model_fast="fast-model", model_strong="strong-model")
    return client, fake


class Person(BaseModel):
    name: str
    age: int


# ---- Test ----
async def test_complete_returns_text() -> None:
    client, fake = _make_client(["Xin chào"])

    out = await client.complete([{"role": "user", "content": "hi"}])

    assert out == "Xin chào"
    # complete() KHÔNG bật JSON mode và mặc định dùng model mạnh.
    call = fake.chat.completions.calls[0]
    # response_format phải VẮNG MẶT hẳn (không phải None): một số endpoint
    # OpenAI-compatible từ chối `"response_format": null` gửi tường minh.
    assert "response_format" not in call
    assert call["model"] == "strong-model"


async def test_complete_json_valid_returns_model() -> None:
    client, fake = _make_client(['{"name": "An", "age": 21}'])

    person = await client.complete_json([{"role": "user", "content": "tạo person"}], Person)

    assert isinstance(person, Person)
    assert person.name == "An"
    assert person.age == 21
    # complete_json() bật JSON mode và mặc định dùng model nhanh.
    call = fake.chat.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["model"] == "fast-model"


async def test_complete_json_retries_on_broken_json_then_succeeds() -> None:
    # Lần 1: không phải JSON → lần 2: JSON đúng.
    client, fake = _make_client(["đây không phải json", '{"name": "Bình", "age": 30}'])

    person = await client.complete_json([{"role": "user", "content": "x"}], Person)

    assert person.name == "Bình"
    assert len(fake.chat.completions.calls) == 2  # đã thử lại đúng 1 lần


async def test_complete_json_retries_on_schema_mismatch() -> None:
    # JSON hợp lệ cú pháp nhưng THIẾU trường 'age' → ValidationError → thử lại.
    client, _fake = _make_client(['{"name": "Chi"}', '{"name": "Chi", "age": 18}'])

    person = await client.complete_json([{"role": "user", "content": "x"}], Person)

    assert person.age == 18


async def test_complete_json_gives_up_raises() -> None:
    # max_retries=2 → tổng 3 lần thử; cả 3 đều hỏng → raise LLMJSONError.
    client, fake = _make_client(["hỏng 1", "hỏng 2", "hỏng 3"])

    with pytest.raises(LLMJSONError):
        await client.complete_json([{"role": "user", "content": "x"}], Person, max_retries=2)

    assert len(fake.chat.completions.calls) == 3


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Cô lập khỏi .env thật của máy dev: chặn load_dotenv + xóa mọi biến liên quan."""
    monkeypatch.setattr("deep_research_agent.core.llm_client.load_dotenv", lambda *a, **k: None)
    for var in (
        "LLM_PROVIDER",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "GEMINI_MODEL_FAST",
        "GEMINI_MODEL_STRONG",
        "GROQ_MODEL_FAST",
        "GROQ_MODEL_STRONG",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


async def test_missing_api_key_raises(clean_env: pytest.MonkeyPatch) -> None:
    # Provider mặc định là gemini → báo thiếu ĐÚNG tên biến của provider đó.
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        LLMClient()  # không truyền client → buộc phải dựng từ key → thiếu key → raise


async def test_missing_api_key_names_the_selected_provider(
    clean_env: pytest.MonkeyPatch,
) -> None:
    # Đổi provider thì thông báo lỗi phải đổi theo — nếu không, user sẽ đi điền nhầm key.
    clean_env.setenv("LLM_PROVIDER", "groq")

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        LLMClient()


async def test_unknown_provider_raises(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("LLM_PROVIDER", "openai")  # chưa hỗ trợ

    with pytest.raises(ValueError, match="không hỗ trợ"):
        LLMClient()


async def test_provider_defaults_and_env_override(clean_env: pytest.MonkeyPatch) -> None:
    """Model lấy đúng theo provider, và biến .env ghi đè được mặc định."""
    fake = FakeLLM([])

    # 1. Không khai báo gì → mặc định của gemini.
    gemini = LLMClient(client=fake)
    assert gemini.provider == "gemini"
    assert gemini.model_fast == "gemini-flash-lite-latest"
    assert gemini.model_strong == "gemini-flash-latest"

    # 2. Đổi provider → bộ model mặc định đổi theo (không lẫn tên model của hãng kia).
    groq = LLMClient(client=fake, provider="groq")
    assert groq.model_strong == "llama-3.3-70b-versatile"

    # 3. Biến môi trường theo tiền tố provider ghi đè mặc định.
    clean_env.setenv("GEMINI_MODEL_STRONG", "gemini-3.5-flash")
    assert LLMClient(client=fake).model_strong == "gemini-3.5-flash"


async def test_gemini_uses_openai_compatible_base_url(clean_env: pytest.MonkeyPatch) -> None:
    """Đây là mấu chốt khiến đổi provider chỉ tốn 1 file: cùng SDK, khác base_url."""
    clean_env.setenv("GEMINI_API_KEY", "fake-key")

    client = LLMClient()

    assert "generativelanguage.googleapis.com" in client.config.base_url
    assert client.config.base_url.endswith("/openai/")
