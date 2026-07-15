# PROGRESS — Deep Research Agent

> **Nhật ký tiến độ theo phiên.** File này thay đổi nhanh (cập nhật mỗi phiên làm việc).
> Quy ước & kiến trúc *bền vững* nằm ở `CLAUDE.md` — KHÔNG lặp lại ở đây.
> **Cách cập nhật:** thêm một entry mới lên ĐẦU mục "Nhật ký phiên" sau mỗi phiên
> hoặc sau mỗi mục checklist hoàn thành. Ghi: đã làm gì · quyết định gì · verify ra sao · bước tiếp.

---

## 📌 Trạng thái hiện tại
- **Giai đoạn:** Tuần 1 — Core loop chạy được.
- **Vừa xong:** Setup skeleton repo (src-layout, uv + hatchling, `.env.example`) — commit `73eacca`.
- **Môi trường:** `uv sync` OK; package `deep_research_agent` cài editable; `import` → `0.1.0`.
- **⚠️ Đang treo:** commit skeleton **CHƯA push** lên `origin/main` (local đang *ahead 1*).

## ⏭️ Việc tiếp theo
1. **(Cần bạn quyết)** Push skeleton lên GitHub hay để sau.
2. Tool layer — `src/deep_research_agent/tools/search.py`: hàm `search(query)` gọi Tavily + test mock (pytest).
3. Tool layer — `src/deep_research_agent/tools/fetch.py`: hàm `fetch_url(url)` dùng `httpx` + `trafilatura` + test.

---

## 🗒️ Nhật ký phiên (mới nhất ở trên)

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
