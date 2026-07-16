"""Test cho ``LLMClient``.

Ta dựng một Groq GIẢ mô phỏng đúng hình dạng response thật
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


class FakeGroq:
    """Đóng thế ``AsyncGroq``: trả lần lượt các nội dung trong ``contents``."""

    def __init__(self, contents: list[str]) -> None:
        self.chat = _FakeChat(contents)


def _make_client(contents: list[str]) -> tuple[LLMClient, FakeGroq]:
    fake = FakeGroq(contents)
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
    assert call["response_format"] is None
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


async def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deep_research_agent.core.llm_client.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        LLMClient()  # không truyền client → buộc phải dựng từ key → thiếu key → raise
