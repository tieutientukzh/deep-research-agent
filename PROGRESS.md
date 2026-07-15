# PROGRESS — Deep Research Agent

> **Nhật ký tiến độ theo phiên.** File này thay đổi nhanh (cập nhật mỗi phiên làm việc).
> Quy ước & kiến trúc *bền vững* nằm ở `CLAUDE.md` — KHÔNG lặp lại ở đây.
> **Cách cập nhật:** thêm một entry mới lên ĐẦU mục "Nhật ký phiên" sau mỗi phiên
> hoặc sau mỗi mục checklist hoàn thành. Ghi: đã làm gì · quyết định gì · verify ra sao · bước tiếp.

---

## 📌 Trạng thái hiện tại
- **Giai đoạn:** Tuần 1 — Core loop chạy được.
- **Vừa xong:** Setup skeleton repo + hệ thống nhật ký tiến độ (PROGRESS.md + CLAUDE.md auto-load).
- **Môi trường:** `uv sync` OK; package `deep_research_agent` cài editable; `import` → `0.1.0`.
- **Git:** skeleton + progress setup đã **push** lên `origin/main`; local & remote đồng bộ.

## ⏭️ Việc tiếp theo
1. Tool layer — `src/deep_research_agent/tools/search.py`: hàm `search(query)` gọi Tavily + test mock (pytest).
2. Tool layer — `src/deep_research_agent/tools/fetch.py`: hàm `fetch_url(url)` dùng `httpx` + `trafilatura` + test.

---

## 🗒️ Nhật ký phiên (mới nhất ở trên)

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
