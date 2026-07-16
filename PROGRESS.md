# PROGRESS — Deep Research Agent

> **Nhật ký tiến độ theo phiên.** File này thay đổi nhanh (cập nhật mỗi phiên làm việc).
> Quy ước & kiến trúc *bền vững* nằm ở `CLAUDE.md` — KHÔNG lặp lại ở đây.
> **Cách cập nhật:** thêm một entry mới lên ĐẦU mục "Nhật ký phiên" sau mỗi phiên
> hoặc sau mỗi mục checklist hoàn thành. Ghi: đã làm gì · quyết định gì · verify ra sao · bước tiếp.

---

## 📌 Trạng thái hiện tại
- **Giai đoạn:** Tuần 1 — Core loop chạy được.
- **Vừa xong:** Tool layer `search()` + `fetch_url()` (async) + `core/schemas.py`; 8 test pytest xanh, ruff + mypy sạch.
- **Môi trường:** `uv sync` OK; `asyncio_mode=auto` cho pytest-asyncio; test không gọi mạng thật (fake client + httpx_mock).
- **Git:** commit `6657a86` (gitignore Note.md) chưa push; tool layer sắp commit.

## ⏭️ Việc tiếp theo
1. `core/llm_client.py`: wrapper Groq, structured output (ép JSON + parse an toàn + retry khi JSON hỏng).
2. ReAct loop đơn giản nhất: 1 agent, 2 tool, parse JSON tool call, tối đa 10 bước.

---

## 🗒️ Nhật ký phiên (mới nhất ở trên)

### 2026-07-16 — Tool layer: search() + fetch_url() + test (Tuần 1, mục 2)
**Đã làm**
- `core/schemas.py`: pydantic `SearchResult` (title/url/snippet/score) + `FetchResult`
  (url/text/error/status_code + property `ok`). Đây là "hợp đồng" dữ liệu chung tool↔agent.
- `tools/search.py`: `async search(query, *, max_results=5, client=None)` → `AsyncTavilyClient`,
  map `results[].content` → `snippet`. Thiếu `TAVILY_API_KEY` → raise rõ ràng.
- `tools/fetch.py`: `async fetch_url(url, *, timeout=10, client=None)` → httpx (follow_redirects,
  User-Agent) + `trafilatura.extract`. **Không raise**: lỗi mạng / non-200 / trang rỗng đều
  trả `FetchResult` có `error` → pipeline sống sót khi gặp URL hỏng.
- `tests/tools/`: 4 test search (fake client) + 4 test fetch (`httpx_mock`) — **không gọi mạng**.

**Quyết định chốt với user**
- **Async** thay vì sync (user đổi ý giữa chừng) — dọn sẵn cho fetch song song sau này.
- **Dependency Injection** (`client=None`): test truyền client giả → không cần mock lib, không cần key.
- Kiểu trả về = **pydantic** đặt tập trung ở `core/schemas.py`.
- **Docstring/comment viết bằng tiếng Việt** (user yêu cầu, override quy ước "comment tiếng Anh").

**Verify**
- `uv run pytest -v` → **8 passed**. `uv run ruff check .` → sạch. `uv run mypy src` → sạch
  (thêm override `ignore_missing_imports` cho `tavily.*` vì lib thiếu stub).
- Bật `asyncio_mode = "auto"` trong `pyproject.toml` để test async không cần decorator.

### 2026-07-16 — Nhật ký tiến độ "bán tự động" + push lên GitHub
- Tạo `PROGRESS.md`; nối `@PROGRESS.md` vào `CLAUDE.md` (auto-load) + thêm quy ước tự cập nhật.
- Đổi tên `Claude.md` → `CLAUDE.md` (chuẩn Linux/CI). Commit `3c440cf`.
- **Push:** đẩy 2 commit (`73eacca`, `3c440cf`) lên `origin/main` — thành công, không cần auth.

### 2026-07-16 — Setup skeleton repo (Tuần 1, mục 1)
**Đã làm**
- `pyproject.toml`: uv + hatchling backend; core deps (groq, tavily-python, httpx, trafilatura, pydantic, tenacity, python-dotenv); extras `api`/`ui`/`obs`; nhóm `dev` (pytest, ruff, mypy…); cấu hình ruff/mypy/pytest.
- Cây src-layout `src/deep_research_agent/{agents,tools,core,storage,observability,api}` — chỉ docstring, **chưa có logic**. Thêm `tests/`, `ui/`, `eval/`.
- `.env.example` (mirror `GROQ_API_KEY`, `TAVILY_API_KEY` + key dự kiến, commented).
- Sửa `.gitignore` (+`*.db`, `data/`, `reports/`, `outputs/`), `Claude.md` (sơ đồ + tech stack theo src-layout/uv), `README.md` (mục Getting started uv).

**Quyết định chốt với user**
- Package layout: **src-layout + package thật `deep_research_agent`** (import tuyệt đối `from deep_research_agent...`).
- Tooling: **uv** (dependency + venv) + **hatchling** (build backend); commit `uv.lock`.

**Verify**
- `uv sync` → build + install editable `deep-research-agent==0.1.0` OK.
- `import deep_research_agent` → `0.1.0`. `uv run pytest` → "no tests ran" (đúng, chưa có test).
- `.env` và `.venv` KHÔNG bị commit (đã ignore).

**Git:** commit `73eacca` (16 files). **Chưa push.**
