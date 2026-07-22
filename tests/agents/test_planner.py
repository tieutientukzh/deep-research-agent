"""Test cho Planner (``agents/planner.py``) — dùng fixture ``make_llm`` từ conftest."""

from __future__ import annotations

from deep_research_agent.agents.planner import plan_research


async def test_parses_sub_questions_and_uses_fast_model(make_llm) -> None:
    llm, fake = make_llm(['{"sub_questions": ["What is X?", "How does X work?", "X vs Y?"]}'])

    questions = await plan_research("topic X", llm=llm)

    assert questions == ["What is X?", "How does X work?", "X vs Y?"]
    # Planning là task nhẹ → dùng model FAST (đúng CLAUDE.md).
    call = fake.chat.completions.calls[0]
    assert call["model"] == "fast-model"
    assert call["response_format"] == {"type": "json_object"}


async def test_clamps_to_max_questions(make_llm) -> None:
    eight = [f"q{i}" for i in range(1, 9)]
    llm, _ = make_llm(['{"sub_questions": ' + str(eight).replace("'", '"') + "}"])

    questions = await plan_research("topic", llm=llm, max_questions=6)

    assert len(questions) == 6
    assert questions == eight[:6]


async def test_strips_and_dedupes(make_llm) -> None:
    llm, _ = make_llm(['{"sub_questions": ["q1", " q1 ", "", "   ", "q2"]}'])

    questions = await plan_research("topic", llm=llm)

    # "q1" và " q1 " (sau strip) trùng → giữ một; câu rỗng/khoảng trắng bị bỏ.
    assert questions == ["q1", "q2"]


async def test_falls_back_to_topic_when_all_empty(make_llm) -> None:
    llm, _ = make_llm(['{"sub_questions": ["   ", ""]}'])

    questions = await plan_research("my topic", llm=llm)

    # Model trả toàn câu rỗng → vẫn cho pipeline sống bằng chính chủ đề.
    assert questions == ["my topic"]
