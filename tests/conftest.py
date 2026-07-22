"""Fixture dùng chung cho toàn bộ test — không test nào chạm mạng thật.

``FakeGroq`` đóng thế ``AsyncGroq``: mô phỏng đúng hình dạng response thật
(``response.choices[0].message.content``) và trả nội dung theo HÀNG ĐỢI, nhờ đó mô phỏng
được cả chuỗi quyết định của agent lẫn tình huống "lần 1 JSON hỏng, lần 2 đúng".

pytest tự nạp ``conftest.py`` này cho mọi test ở các thư mục con → fixture ``make_llm`` và
``decision`` dùng được ở khắp nơi mà không cần import.

Ghi chú: ba file test cũ (test_llm_client / test_agent_loop / test_pipeline) hiện vẫn giữ
bản ``FakeGroq`` cục bộ của riêng chúng; có thể dời chúng sang đây sau (dọn dẹp, không gấp).
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from deep_research_agent.core.llm_client import LLMClient


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
    """Trả lần lượt các nội dung trong ``contents`` mỗi lần ``chat.completions.create``."""

    def __init__(self, contents: list[str]) -> None:
        self.chat = _FakeChat(contents)


@pytest.fixture
def make_llm() -> Callable[..., tuple[LLMClient, FakeGroq]]:
    """Factory: ``make_llm(contents) -> (llm, fake)`` — LLM bọc FakeGroq trả theo hàng đợi."""

    def _factory(
        contents: list[str],
        *,
        model_fast: str = "fast-model",
        model_strong: str = "strong-model",
    ) -> tuple[LLMClient, FakeGroq]:
        fake = FakeGroq(contents)
        llm = LLMClient(client=fake, model_fast=model_fast, model_strong=model_strong)
        return llm, fake

    return _factory


@pytest.fixture
def decision() -> Callable[..., str]:
    """Factory: dựng JSON một ``AgentDecision`` — đúng thứ model thật trả về trong JSON mode."""

    def _decision(action: str, args: dict | None = None, thought: str = "t") -> str:
        return json.dumps({"thought": thought, "action": action, "args": args or {}})

    return _decision
