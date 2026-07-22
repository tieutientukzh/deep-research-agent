# PROGRESS — Deep Research Agent

> **Nhật ký tiến độ theo phiên.** File này thay đổi nhanh (cập nhật mỗi phiên làm việc).
> Quy ước & kiến trúc *bền vững* nằm ở `CLAUDE.md` — KHÔNG lặp lại ở đây.
> **Cách cập nhật:** thêm một entry mới lên ĐẦU mục "Nhật ký phiên" sau mỗi phiên
> hoặc sau mỗi mục checklist hoàn thành. Ghi: đã làm gì · quyết định gì · verify ra sao · bước tiếp.

---

## 📌 Trạng thái hiện tại
- **Giai đoạn:** 🚧 **Tuần 2 — Kiến trúc đầy đủ.** ✅ Mục 1 (Planner + Researcher loop) XONG.
- **Vừa xong:** **Planner + Researcher (deep mode)** — `plan_research` phân rã topic thành
  3-6 sub-question (model fast); mỗi sub-question chạy `run_agent` (ReAct) với **model strong
  70B + guard `validate_finish`** (ép fetch ≥1 nguồn trước khi finish); `SourceRegistry` giữ
  citation `[n]` toàn cục (dedupe URL); `run_deep_pipeline` gộp lại → Writer. CLI thêm
  `--mode deep|simple` (mặc định deep). **41 test xanh**, ruff + mypy sạch. Smoke API thật
  (deep + simple) PASS (xem entry mới nhất). Kiến thức phiên ghi vào `NOTE.md`.
- **Môi trường:** `uv sync` OK; `asyncio_mode=auto`; test dùng fake/mock, không gọi mạng thật.
  ⚠️ `pytest.exe` bị Windows Application Control chặn (os error 4551) → chạy
  `uv run python -m pytest` (KHÔNG `uv run pytest`).
- **Git:** đã **push** tới `a3a23bd`; commit pipeline (T1) + commit deep mode (phiên này) đang chờ push.

## ⏭️ Việc tiếp theo
1. Tuần 2, mục 2: **Điều kiện dừng thông minh** — hiện Researcher chỉ có guard "≥1 nguồn" +
   `max_steps`. Thêm tự đánh giá `sufficient/missing` (structured output) để dừng có lý trí.
2. Tuần 2, mục 3: **Note-taker** — nén mỗi nguồn thành notes đều nhau, gắn `[source_id]`
   → xử lý finding "Writer bỏ sót/lệch nguồn" (smoke test deep: `[3]` liệt kê nhưng không cite).
3. Dọn dẹp nhỏ (không gấp): 3 file test cũ vẫn có `FakeGroq` cục bộ — dời sang `tests/conftest.py`
   (đã có fixture `make_llm`/`decision` dùng chung cho test mới).

---

## 🗒️ Nhật ký phiên (mới nhất ở trên)

### 2026-07-22 — Planner + Researcher loop mỗi sub-question (Tuần 2, mục 1)
**Đã làm**
- `core/schemas.py`: thêm `ResearchPlan` (structured output Planner — chỉ validate ≥1 câu,
  clamp trần để trong code), `SubQuestionResult` (question/answer/source_ids/stopped_by_limit),
  `PipelineResult.sub_questions`. Dời type alias `SearchFn`/`FetchFn` về đây (nơi trung lập)
  để pipeline ↔ researcher không import vòng.
- `core/sources.py` (MỚI): `SourceRegistry` — sổ cái nguồn dùng chung, cấp id `[n]` toàn cục,
  **dedupe theo URL** xuyên các sub-question; truncate text ~6000 ký tự.
- `core/agent_loop.py`: `run_agent` thêm 2 param backward-compatible — `model` (truyền xuống
  `complete_json`) và `validate_finish` (hook chặn `finish`, trả lỗi → observation cho model sửa).
- `agents/planner.py` (MỚI): `plan_research(topic, *, llm, max_questions=6)` — model FAST, prompt
  yêu cầu 3-6 sub-question cùng ngôn ngữ topic; code strip/dedupe/clamp, fallback về topic nếu rỗng.
- `agents/researcher.py` (MỚI): `research_sub_question(...)` — dựng tool registry closure bọc
  `search_fn`/`fetch_fn` + `registry` + `on_progress`; fetch thành công → `registry.add` (agent
  không biết); guard closure ép fetch ≥1 nguồn trước finish; gọi `run_agent(model=strong)`.
- `pipeline.py`: `run_deep_pipeline` (Planner → mỗi sub-question chạy Researcher tuần tự, chung
  1 registry → Writer 1 lượt với prompt deep mở rộng: nhận research notes + nguồn `[n]`). **Giữ
  nguyên `run_pipeline` cũ** làm baseline cho ablation Tuần 3.
- `__main__.py`: flag `--mode deep|simple` (mặc định deep).
- Test: `tests/conftest.py` (MỚI — fixture `make_llm`/`decision` dùng chung); `tests/agents/`
  test_planner (4) + test_researcher (4); mở rộng test_agent_loop (model passthrough,
  validate_finish) + test_pipeline (deep happy path, 0 nguồn → error không gọi Writer).

**Quyết định chốt với user**
- **Researcher dùng model STRONG 70B + guard code** (không phải fast/prompt-only): thứ tự tin
  cậy `code > model > prompt` (defense in depth) — xem `NOTE.md` mục [2026-07-22].
- **Kéo trước một phần mục 4 (SourceRegistry)** vào phiên này để deep mode không mất citation
  `[n]` — nếu chỉ đưa answer text tự do cho Writer thì báo cáo thụt lùi so với T1.

**Verify**
- `uv run python -m pytest -q` → **41 passed** (29 cũ + 12 mới). `ruff check .` sạch. `mypy src` sạch.
- **Smoke test API thật (Groq + Tavily) — PASS**:
  - **deep**: "So sánh LoRA và QLoRA khi fine-tune LLM" → Planner ra 5 sub-question tiếng Việt;
    mỗi sub-question fetch nguồn thật (guard hoạt động — không còn cảnh trả lời từ mỗi snippet);
    dedupe (vmixvietnam fetch ở sub-q1 & sub-q5 → cùng `[1]`) → 5 nguồn; báo cáo có citation
    `[1]..[5]` + `## Sources`.
  - **simple**: "What is FAISS?" → baseline vẫn chạy, skip URL 403 rồi lấy URL kế → 3 nguồn.
- ✅ **Cải thiện so với T1:** citation đã **cân bằng across nguồn** (`[1][2][4][5]` đều được cite),
  không còn dồn về 1 nguồn như finding T1.
- ⚠️ **Finding:** Writer vẫn bỏ sót nguồn (`[3]` liệt kê nhưng không cite trong thân bài) → để
  Note-taker (mục 3) + prompt Writer chặt hơn xử lý.

### 2026-07-19 — pipeline.py: pipeline thô end-to-end (Tuần 1, mục 5 — Milestone T1 ✅)
**Đã làm**
- `core/schemas.py`: thêm `Source` (id/title/url/text — `id` chính là số citation `[n]`)
  và `PipelineResult` (topic/report/sources/skipped_urls/error).
- `pipeline.py` (top-level package): `run_pipeline(topic, *, llm, min_sources=3,
  max_sources=5, search_max_results=8, search_fn, fetch_fn, on_progress)`:
  - Flow **deterministic**: search 1 lần (topic làm query) → fetch tuần tự URL theo rank
    (dedupe; URL hỏng → `skipped_urls`, thử URL kế) → đủ `max_sources` thì dừng →
    1 lời gọi `llm.complete` (model strong) viết báo cáo Markdown.
  - Text mỗi nguồn cắt 6000 ký tự. 0 nguồn sống → trả `error`, KHÔNG gọi LLM. Dưới
    `min_sources` → vẫn viết nhưng cảnh báo qua `on_progress`.
  - Prompt writer: báo cáo theo ngôn ngữ topic, cite `[n]` sau mỗi claim, cuối bài mục
    `## Sources`. TODO Tuần 2: delimiter chống prompt injection.
- `__main__.py`: CLI `python -m deep_research_agent "<topic>"` — progress ra stderr,
  báo cáo ra stdout + lưu `reports/<slug>-<timestamp>.md` (gitignored).
- `tests/test_pipeline.py`: 7 test (fake search/fetch qua DI + FakeGroq soi được prompt):
  happy path (đúng max_sources, id 1..n, prompt chứa nguồn, dùng model strong); skip URL
  hỏng lấy URL kế; 0 nguồn → error không gọi LLM; search rỗng → error; < min_sources vẫn
  ra báo cáo + warning; dedupe URL; text dài bị cắt trong prompt.

**Quyết định chốt với user**
- **Hướng A — pipeline cố định (deterministic)** thay vì dựa trên ReAct loop: giải quyết
  triệt để finding "agent lười fetch" (code ép fetch 100%), rẻ (1 lời gọi LLM/run), dễ
  test. `run_agent` giữ nguyên làm nền cho Researcher Tuần 2.

**Verify**
- `uv run pytest -v` → **29 passed** (22 cũ + 7 mới). `ruff check .` sạch. `mypy src` sạch.
- **Smoke test API thật (Groq + Tavily) — PASS**: topic "So sánh FAISS và ChromaDB cho
  semantic search" → fetch 5/5 nguồn (0 skip) → báo cáo tiếng Việt đúng cấu trúc, có
  citation `[n]` + mục `## Sources`, lưu file vào `reports/`. **Milestone T1 đạt.**
- ⚠️ **Finding 1:** hầu hết claim chỉ cite `[2]` (bài Medium) — các nguồn YouTube/Scribd
  trafilatura trích được rất ít text hữu ích nhưng vẫn đếm là "nguồn ok" → cần bước chọn
  URL đáng đọc / lọc chất lượng nguồn (Tuần 2).
- ⚠️ **Finding 2:** Writer không tự cân bằng citation giữa các nguồn → Note-taker (nén
  nguồn thành notes đều nhau) + prompt Writer chặt hơn sẽ xử lý ở Tuần 2.

### 2026-07-17 — agent_loop.py: ReAct loop tối giản (Tuần 1, mục 4)
**Đã làm**
- `core/schemas.py`: thêm `AgentDecision` (thought/action/args), `AgentStep` (decision +
  observation — lịch sử để debug/SQLite sau này), `AgentResult` (answer/steps/stopped_by_limit).
- `core/agent_loop.py`:
  - `ToolSpec` (description cho prompt + `args_schema` pydantic + hàm `run` async) và
    **tool registry** dict `{"search": ..., "fetch_url": ...}` — injectable để test.
  - `run_agent(task, *, llm, tools=None, max_steps=10)`: vòng Reason→Act→Observe.
    Mỗi vòng gọi `complete_json` ép `AgentDecision` → validate args bằng schema con →
    gọi tool → kết quả thành observation (message `role="user"`, prefix `[Observation]`).
  - Format observation: search = danh sách đánh số `n. title — url — snippet` (snippet
    cắt 300 ký tự); fetch cắt 4000 ký tự + marker `...[truncated]`; fetch hỏng → báo lỗi
    để agent chọn URL khác.
  - System prompt tiếng Anh sinh từ registry; để sẵn TODO chỗ chèn delimiter chống
    injection (Tuần 2).
- `tests/core/test_agent_loop.py`: 8 test — happy path (search→fetch→finish, kiểm cả
  messages đưa lại LLM); action lạ / args thiếu / finish thiếu answer → observation lỗi
  rồi tự sửa; chạm `max_steps` → `stopped_by_limit`; 3 test runner mặc định (format
  search, fetch lỗi, cắt text dài) qua monkeypatch.

**Quyết định thiết kế**
- **Lỗi của model là observation, không phải exception**: action lạ/args sai → đưa thông
  báo lỗi vào hội thoại cho model tự sửa (chỉ `LLMJSONError` mới propagate — lỗi hạ tầng).
- **`action: str` thay vì `Literal`** (lệch nhẹ so với plan đã duyệt, đã nêu lý do khi code):
  Literal sẽ làm action lạ fail ngay trong retry của `complete_json` → crash, và hardcode
  tên tool vào schema trong khi registry là injectable.
- `finish` là action giả với args `{"answer": ...}` — model tự tuyên bố xong.
- Observation qua message `role="user"` (không dùng `role="tool"` native) — đúng mục tiêu
  tự viết function calling qua JSON.

**Verify**
- `uv run pytest -v` → **22 passed** (14 cũ + 8 mới). `ruff check .` sạch. `mypy src` sạch.
- **Smoke test với API thật (Groq + Tavily) — PASS**: task "PhoBERT là gì và do ai phát
  triển?" → agent tự search 3 lần → finish với answer đúng (VinAI Research), 4 bước,
  `stopped_by_limit=False`, JSON tool calling không lỗi lần nào.
- ⚠️ **Finding:** agent (model fast `llama-3.1-8b-instant`) trả lời CHỈ từ snippet, không
  hề gọi `fetch_url` dù prompt đã gợi ý — với câu hỏi khó hơn sẽ thiếu chiều sâu. Xử lý ở
  pipeline (mục 5): ép flow fetch nguồn, hoặc dùng model strong cho quyết định.

### 2026-07-16 — llm_client.py: wrapper Groq + structured output (Tuần 1, mục 3)
**Đã làm**
- `core/llm_client.py`: `class LLMClient` (async) — bọc `AsyncGroq`, gom cấu hình model
  fast/strong + API key về một chỗ.
  - `complete(messages, *, model, temperature)`: sinh text thường (mặc định model mạnh).
  - `complete_json(messages, schema, *, model, max_retries=2)`: bật Groq JSON mode →
    `json.loads` → validate vào pydantic `schema`. Hỏng thì **nhét output hỏng + lỗi ngược
    lại cho model** để "sửa bài", thử tối đa `max_retries` lần; hết lượt → raise `LLMJSONError`.
  - Generic `TypeVar T bound=BaseModel` để `complete_json` trả đúng kiểu schema (không phải Any).
- `tests/core/test_llm_client.py`: fake `AsyncGroq` trả nội dung theo hàng đợi (mô phỏng
  "lần 1 hỏng, lần 2 đúng"). 6 ca: complete text; JSON hợp lệ; retry khi JSON hỏng; retry khi
  sai schema (thiếu field); hết lượt → raise; thiếu API key → raise.

**Quyết định chốt với user**
- **Class `LLMClient`** (thay vì hàm rời) — giữ state cấu hình, dễ test qua DI.
- **Retry chỉ cho JSON hỏng** trong Tuần 1; backoff lỗi mạng/rate-limit để Tuần 2 (đúng roadmap).
- Dùng `response_format={"type":"json_object"}` (JSON mode chạy mọi model) + tự validate pydantic.

**Verify**
- `uv run pytest -v` → **14 passed**. `ruff check .` sạch. `mypy src` sạch
  (cần 2 `# type: ignore[arg-type]` ở lời gọi Groq vì SDK dùng TypedDict chặt).

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
