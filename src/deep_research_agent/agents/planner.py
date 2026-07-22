"""Planner — phân rã một chủ đề nghiên cứu thành 3-6 sub-question độc lập.

Đây là bước [1] trong kiến trúc đích: thay vì "search thẳng chủ đề" (pipeline thô T1), ta
để LLM chia chủ đề thành các câu hỏi con, mỗi câu sẽ được Researcher nghiên cứu riêng. Nhờ
vậy báo cáo có cấu trúc và bao phủ nhiều khía cạnh hơn.

Ghi chú thiết kế:
- **Dùng model FAST** (đúng CLAUDE.md): phân rã chủ đề là task ngắn, có cấu trúc, không cần
  model mạnh — để dành 70B cho Researcher (chọn URL/query) và Writer (tổng hợp).
- **Structured output** qua ``complete_json(ResearchPlan)``: model buộc trả JSON đúng
  schema, khỏi tự parse danh sách bằng regex.
- **Làm sạch trong code, không siết trong schema**: strip khoảng trắng, bỏ câu rỗng, dedupe,
  và clamp trần ``max_questions``. Cố ý clamp ở đây thay vì trong ``ResearchPlan`` — model
  lỡ trả thừa câu là chuyện code xử được, không đáng để ``complete_json`` tốn retry rồi crash.
"""

from __future__ import annotations

from deep_research_agent.core.llm_client import LLMClient, Message
from deep_research_agent.core.schemas import ResearchPlan

# Prompt tiếng Anh (LLaMA bám instruction/JSON ổn định hơn); nội dung sub-question vẫn theo
# ngôn ngữ của chủ đề để cả pipeline nhất quán ngôn ngữ với người dùng.
_PLANNER_SYSTEM_PROMPT = """\
You are a research planner. Given a research topic, break it down into a small set of \
focused sub-questions that, if answered, would together cover the topic well.

Rules:
- Produce between 3 and 6 sub-questions.
- Each sub-question must be self-contained and independently researchable via web search.
- Cover distinct angles; do NOT restate the same question in different words.
- Write the sub-questions in the SAME LANGUAGE as the topic.
- Reply with ONLY a JSON object: {"sub_questions": ["...", "..."]}
"""


async def plan_research(
    topic: str,
    *,
    llm: LLMClient,
    max_questions: int = 6,
) -> list[str]:
    """Phân rã ``topic`` thành danh sách sub-question (đã làm sạch, tối đa ``max_questions``).

    Args:
        topic: chủ đề nghiên cứu người dùng nhập.
        llm: client LLM; bước này dùng model fast (task planning nhẹ).
        max_questions: trần số sub-question giữ lại (clamp trong code).

    Returns:
        Danh sách sub-question không rỗng, đã strip/dedupe/clamp. Nếu model trả toàn câu
        rỗng (hiếm) thì fallback về chính ``topic`` để pipeline vẫn chạy được.
    """
    messages: list[Message] = [
        {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Topic: {topic}"},
    ]
    plan = await llm.complete_json(messages, ResearchPlan, model=llm.model_fast)

    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in plan.sub_questions:
        question = raw.strip()
        if not question or question in seen:
            continue
        seen.add(question)
        cleaned.append(question)

    if not cleaned:
        # Model trả rỗng/toàn khoảng trắng → vẫn cho pipeline sống bằng chính chủ đề.
        return [topic]
    return cleaned[:max_questions]
