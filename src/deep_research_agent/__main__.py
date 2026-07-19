"""CLI tối giản: ``python -m deep_research_agent "<chủ đề>"``.

Chạy pipeline thô end-to-end, in báo cáo Markdown ra stdout (pipe/redirect được) và lưu
một bản vào ``reports/`` (thư mục đã gitignore). Progress in ra stderr để không lẫn vào
báo cáo.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from deep_research_agent.core.llm_client import LLMClient
from deep_research_agent.core.schemas import PipelineResult
from deep_research_agent.pipeline import run_pipeline


def _slugify(text: str, *, max_len: int = 50) -> str:
    """Biến chủ đề thành tên file an toàn: bỏ dấu tiếng Việt, thay ký tự lạ bằng ``-``."""
    # NFKD tách chữ và dấu ("quantization" giữ nguyên, "so sánh" → "so sanh").
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug[:max_len] or "report"


def _save_report(result: PipelineResult) -> Path:
    """Lưu báo cáo vào ``reports/<slug>-<timestamp>.md`` và trả về đường dẫn."""
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = reports_dir / f"{_slugify(result.topic)}-{timestamp}.md"
    assert result.report is not None
    path.write_text(result.report, encoding="utf-8")
    return path


async def _main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m deep_research_agent",
        description="Nghiên cứu một chủ đề: search web, fetch nguồn, viết báo cáo Markdown.",
    )
    parser.add_argument("topic", help="Chủ đề nghiên cứu (tiếng Việt hoặc tiếng Anh)")
    parser.add_argument(
        "--max-sources", type=int, default=5, help="Số nguồn tối đa (mặc định 5)"
    )
    args = parser.parse_args()

    llm = LLMClient()  # raise sớm nếu thiếu GROQ_API_KEY — lỗi cấu hình cần biết ngay
    result = await run_pipeline(args.topic, llm=llm, max_sources=args.max_sources)

    if result.report is None:
        print(f"Pipeline failed: {result.error}", file=sys.stderr)
        return 1

    saved_path = _save_report(result)
    print(result.report)
    print(f"\nReport saved to {saved_path}", file=sys.stderr)
    if result.skipped_urls:
        print(f"Skipped URLs (fetch failed): {len(result.skipped_urls)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
