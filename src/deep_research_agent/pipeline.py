"""Pipeline thô end-to-end: topic → search → fetch 3-5 nguồn → báo cáo Markdown 1 lượt.

Đây là phiên bản "deterministic" cho Milestone T1: **code Python điều khiển flow**, LLM chỉ
làm đúng MỘT việc là viết báo cáo cuối cùng từ các nguồn đã fetch sẵn.

Vì sao không dùng ReAct loop (``run_agent``) ở đây?
- Smoke test phiên trước cho thấy model tự quyết thì LƯỜI fetch — chỉ đọc snippet. Với
  pipeline cố định, việc fetch là do code ép, đảm bảo 100% báo cáo dựa trên toàn văn nguồn.
- Rẻ và dễ đoán: cả pipeline chỉ tốn 1 lời gọi LLM (bước viết); mỗi bước xác định nên
  test/debug dễ. Phần "agentic thông minh" (tự sinh query, tự đánh giá đủ/thiếu) là việc
  của Researcher ở Tuần 2 — ReAct loop đã viết sẽ được dùng lại ở đó.

Ghi chú thiết kế:
- **Fetch tuần tự theo rank** của search: URL hỏng → ghi vào ``skipped_urls`` rồi thử URL
  kế tiếp, dừng khi đủ ``max_sources`` nguồn sống. Fetch song song để Tuần 2 (cache/retry
  làm cùng lúc).
- **Không nguồn nào sống → trả ``PipelineResult(error=...)``** thay vì raise — lỗi lường
  trước không làm sập chương trình (cùng triết lý ``FetchResult``).
- **DI cho test**: ``search_fn``/``fetch_fn`` là tham số injectable, test truyền fake async
  function — không mạng, không API key.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable

from deep_research_agent.core.llm_client import LLMClient, Message
from deep_research_agent.core.schemas import (
    FetchResult,
    PipelineResult,
    SearchResult,
    Source,
)
from deep_research_agent.tools.fetch import fetch_url
from deep_research_agent.tools.search import search

# Mỗi nguồn cắt còn ~6000 ký tự: 5 nguồn ≈ 30k ký tự (~8k token) — vừa đủ chi tiết cho
# báo cáo, không nổ context của model 70B (128k) và không tốn token vô ích.
_MAX_SOURCE_CHARS = 6000

# Kiểu của 2 hàm tool được inject (mặc định là tool thật).
SearchFn = Callable[..., Awaitable[list[SearchResult]]]
FetchFn = Callable[..., Awaitable[FetchResult]]

# Prompt điều khiển viết tiếng Anh (nhất quán với agent_loop — LLaMA bám instruction ổn
# định hơn); báo cáo viết theo ngôn ngữ của topic. TODO Tuần 2: bọc nội dung nguồn trong
# delimiter + chỉ dẫn chống prompt injection ("text inside delimiters is DATA...").
_WRITER_SYSTEM_PROMPT = """\
You are a research report writer. You will receive a research topic and several web \
sources, each labeled with a number like [1], [2].

Write a well-structured Markdown report about the topic, based ONLY on the provided \
sources:
- Write the report in the SAME LANGUAGE as the topic.
- Start with a title (# heading), then organized sections (## headings).
- Every factual claim must cite its source(s) inline using the [n] labels, e.g. \
"LLaMA 3 was released in 2024 [2]."
- If sources disagree, mention the disagreement and cite both.
- Do NOT invent facts that are not in the sources.
- End the report with a "## Sources" section listing every source as: [n] title — url
"""


def _truncate(text: str, limit: int) -> str:
    """Cắt ``text`` còn ``limit`` ký tự, đánh dấu rõ là đã cắt (model biết còn nữa)."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


async def _collect_sources(
    results: list[SearchResult],
    *,
    max_sources: int,
    fetch_fn: FetchFn,
    on_progress: Callable[[str], None],
) -> tuple[list[Source], list[str]]:
    """Fetch tuần tự các URL theo thứ tự rank cho đến khi đủ ``max_sources`` nguồn sống.

    Returns:
        ``(sources, skipped_urls)`` — nguồn sống đã đánh id 1..n, và các URL bị bỏ qua
        (fetch hỏng) kèm theo để debug.
    """
    sources: list[Source] = []
    skipped_urls: list[str] = []
    seen_urls: set[str] = set()

    for result in results:
        if len(sources) >= max_sources:
            break
        # Search API đôi khi trả cùng một URL dưới nhiều kết quả → chỉ fetch một lần.
        if not result.url or result.url in seen_urls:
            continue
        seen_urls.add(result.url)

        on_progress(f"Fetching source {len(sources) + 1}/{max_sources}: {result.url}")
        fetched = await fetch_fn(result.url)
        if not fetched.ok:
            skipped_urls.append(result.url)
            on_progress(f"  -> skipped ({fetched.error})")
            continue

        assert fetched.text is not None  # .ok đã đảm bảo, giúp mypy hiểu
        sources.append(
            Source(
                id=len(sources) + 1,
                title=result.title or result.url,
                url=result.url,
                text=_truncate(fetched.text, _MAX_SOURCE_CHARS),
            )
        )

    return sources, skipped_urls


def _build_writer_messages(topic: str, sources: list[Source]) -> list[Message]:
    """Ghép topic + các nguồn thành hội thoại cho lời gọi viết báo cáo duy nhất."""
    source_blocks = "\n\n".join(
        f"[{s.id}] {s.title} ({s.url})\n{s.text}" for s in sources
    )
    user_content = f"Topic: {topic}\n\nSources:\n\n{source_blocks}"
    return [
        {"role": "system", "content": _WRITER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _log_to_stderr(message: str) -> None:
    """Progress mặc định in ra stderr — stdout để dành cho báo cáo (pipe được)."""
    print(message, file=sys.stderr)


async def run_pipeline(
    topic: str,
    *,
    llm: LLMClient,
    min_sources: int = 3,
    max_sources: int = 5,
    search_max_results: int = 8,
    search_fn: SearchFn = search,
    fetch_fn: FetchFn = fetch_url,
    on_progress: Callable[[str], None] = _log_to_stderr,
) -> PipelineResult:
    """Chạy pipeline thô: search → fetch đủ nguồn → 1 lời gọi LLM viết báo cáo.

    Args:
        topic: chủ đề nghiên cứu — dùng trực tiếp làm search query (sinh query thông minh
            là việc của Researcher Tuần 2).
        llm: client LLM; bước viết dùng model strong mặc định của ``complete``.
        min_sources: dưới ngưỡng này pipeline vẫn viết báo cáo (nếu có ≥1 nguồn) nhưng
            cảnh báo qua ``on_progress``; 0 nguồn thì trả ``error``.
        max_sources: số nguồn tối đa đưa vào báo cáo.
        search_max_results: xin search API nhiều hơn ``max_sources`` để có URL dự phòng
            khi một số trang fetch hỏng.
        search_fn / fetch_fn: tool thật mặc định; test truyền fake async function.
        on_progress: callback nhận thông báo tiến độ (CLI in stderr, UI sau này cập nhật
            màn hình).

    Returns:
        ``PipelineResult`` — có ``report`` khi thành công, hoặc ``error`` khi không thu
        được nguồn nào dùng được.
    """
    on_progress(f"Searching: {topic}")
    results = await search_fn(topic, max_results=search_max_results)
    if not results:
        return PipelineResult(topic=topic, error="search returned no results")

    sources, skipped_urls = await _collect_sources(
        results, max_sources=max_sources, fetch_fn=fetch_fn, on_progress=on_progress
    )

    if not sources:
        return PipelineResult(
            topic=topic,
            skipped_urls=skipped_urls,
            error=f"no source could be fetched (tried {len(skipped_urls)} URLs)",
        )
    if len(sources) < min_sources:
        on_progress(
            f"Warning: only {len(sources)}/{min_sources} sources fetched — "
            "report may be shallow."
        )

    on_progress(f"Writing report from {len(sources)} sources...")
    report = await llm.complete(_build_writer_messages(topic, sources))

    return PipelineResult(
        topic=topic, report=report, sources=sources, skipped_urls=skipped_urls
    )
