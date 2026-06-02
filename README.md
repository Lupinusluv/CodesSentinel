# CodeSentinel

> AI-powered code review platform — a multi-agent LangGraph system that audits pull requests in parallel and streams findings to a real-time dashboard.

CodeSentinel ingests Git webhooks, dispatches three specialized review agents (Security / Performance / Style) in parallel via LangGraph, and pushes findings to the browser through Redis Pub/Sub + WebSockets. It is a portfolio project demonstrating production patterns for LLM-driven code analysis: structured agent outputs, RAG-grounded review context, async task pipelines, and — most importantly — **measurable claims backed by a hand-crafted evaluation set**.

### 🔗 Live demo — [tantai.xyz](https://tantai.xyz)

**Try it right now, no signup and no GitHub token.** Open the live instance, go to **🔍 New Review**, paste any code snippet, and watch three agents stream findings in parallel followed by a synthesis report. The full GitHub-PR auto-review flow is described under [Quickstart](#quickstart) below if you want to self-host.

---

## Architecture

```
Git platform Webhook  (GitHub today; GitLab/Gitee on roadmap)
        │
        ▼
   FastAPI ──► ARQ queue ──► review_task
                                  │
                                  ▼
                          ┌───────────────┐
                          │  RAG retrieve │   (pgvector + AST chunker)
                          └───────┬───────┘
                                  ▼
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
            SecurityAgent   PerformanceAgent  StyleAgent     (parallel)
                  │               │               │
                  └───────────────┼───────────────┘
                                  ▼
                          SynthesisAgent           (dedupe + executive summary)
                                  │
                                  ▼
                          Redis Pub/Sub ──► WebSocket ──► React UI
```

Each agent has a narrow system prompt and produces structured Pydantic output. The graph topology is implemented in `backend/app/agents/graph.py` using LangGraph's `StateGraph`. Agents have no side effects — DB writes happen in the task layer (`backend/app/tasks/review_task.py`).

---

## Tech Stack

| Layer        | Choice                                                                            |
|--------------|-----------------------------------------------------------------------------------|
| Backend      | Python 3.11, FastAPI, SQLAlchemy (async), ARQ task queue                          |
| LLM stack    | LangGraph, LangChain, DeepSeek (review LLM) + DashScope (RAG embeddings)           |
| Storage      | PostgreSQL + pgvector, Redis (queue / cache / pub-sub)                            |
| Frontend     | React + TypeScript, Tailwind CSS, shadcn/ui, Monaco Editor                        |
| Infra        | Docker Compose (full stack, healthcheck-based dependency chain), Alembic          |

---

## Quickstart

```bash
git clone https://github.com/<you>/codessentinel.git
cd codessentinel
cp .env.example .env
# edit .env:
#   DEEPSEEK_API_KEY  — required: the review LLM. No key → reviews can't run.
#   DASHSCOPE_API_KEY — required field, used for RAG embeddings (DeepSeek has no
#                       embeddings endpoint, so vectors go through DashScope/Aliyun).
#                       Keep the .env.example placeholder so the backend boots; RAG
#                       degrades gracefully if the key is fake/empty. Don't delete
#                       the line — it's a required field and an empty value will fail.
#   DATABASE_URL / REDIS_URL — overridden by compose, no need to touch.

docker compose up -d
# postgres + redis + backend (with alembic migration) + worker + frontend
# wait for healthchecks; backend serves on :8000, frontend on :5173
```

Open **http://localhost:5173**. There are two ways to use it — **you never edit code inside the tool itself**:

### A. Paste mode (zero setup beyond the LLM key)
On the home page (**🔍 New Review**), paste a snippet, pick a language, and hit **开始审查**. The three agents (Security / Performance / Style) stream findings live, followed by a synthesis report. This is the fastest way to try it — **no GitHub, no token, no webhook needed**, just `DEEPSEEK_API_KEY`.

### B. GitHub PR mode (auto-review every pull request)
Let CodeSentinel review your real PRs automatically. GitHub must be able to reach your backend's webhook endpoint, so the backend has to be **publicly reachable** — a cloud server, or a tunnel like `ngrok http 8000` from a laptop. Then:

1. **Register the repo** — 🗂 Repos page → repo URL + a webhook secret.
2. **Add the GitHub webhook** — repo Settings → Webhooks → Add:
   - Payload URL: `http://<public-addr>:8000/api/v1/webhooks/github`
   - Content type `application/json`, Secret = the same string, Events = **Pull requests** only.
   - The secret must match in **all three places** (GitHub webhook config / repo registration / `.env` `GITHUB_WEBHOOK_SECRET`), and the repo URL must match GitHub's `html_url` exactly.
3. *(Optional)* **Index the repo** for RAG — 🗂 Repos → 触发索引, so reviews can cite related code from the same repo. Needs a valid `DASHSCOPE_API_KEY` and source files on the default branch.
4. Open a PR → the commit gets a CodeSentinel status check + a review comment.

> Only **pull-request** events trigger a review (`opened` / `synchronize` / `reopened`). Pushing straight to a branch without opening a PR won't be reviewed.

To run the evaluation locally (no Docker required, just `DEEPSEEK_API_KEY` and a placeholder `DATABASE_URL` for pydantic-settings validation):

```bash
cd backend
python scripts/run_eval.py                  # all 40 samples (~8 min)
python scripts/run_eval.py --subset security # subset smoke test
```

Results land in `backend/scripts/eval_results/<timestamp>.json` with incremental per-sample writes.

---

## Evaluation

The project ships a hand-crafted evaluation set and a comparison script that pits the multi-agent system against a single-LLM baseline using the same input, the same model, and the same `temperature=0`. Both pipelines are scored against a shared expected-issues ground truth.

### Per-Category Results (the headline)

After three iteration rounds, the multi-agent system **outperforms the single-LLM baseline in all three per-category F1 scores**:

| Category    | Multi-Agent F1 | Baseline F1 | Δ      |
|-------------|----------------|-------------|--------|
| Security    | **59%**        | 52%         | **+7** |
| Performance | **74%**        | 74%         | tied   |
| Style       | **50%**        | 40%         | **+10**|

(Per-category precision/recall details in `backend/scripts/eval_results/20260525_133402.json`.)

### Overall Results & Iteration History

| Version              | Multi-Agent F1 | Precision | Recall | Notes                                                          |
|----------------------|----------------|-----------|--------|----------------------------------------------------------------|
| v0.2 (initial)       | 32.2%          | 19.6%     | 90.7%  | Cross-category pollution, no lane discipline                   |
| v0.3-rc              | 40.9%          | 27.1%     | 83.7%  | Lane discipline + perf whitelist; style over-suppressed        |
| **v0.3 (Path X)**    | **41.3%**      | 26.7%     | 90.7%  | + softened style prompt + expanded keyword set (see below)     |
| **Single-LLM baseline** | **45.2%**   | 30.4%     | 88.4%  | Same model, same input, single call with a unified prompt      |

The overall F1 sits ~4 points below the baseline because the multi-agent system produces **~1.5× more predictions per sample** (three agents fan out, even after de-duplication), which slightly lowers overall precision. In per-category breakdowns this disadvantage disappears: each agent only contests issues in its own lane.

### How the Iterations Moved the Numbers

1. **v0.2 → v0.3-rc** (+8.7 F1): Lane discipline in all three prompts; a strict 7-pattern whitelist for the Performance agent (N+1, blocking I/O in async, sort-for-max, etc.) — explicitly forbidding vague advice like "consider caching".
2. **v0.3-rc → v0.3 / Path X** (+0.4 F1, but recall recovered from 83.7% to 90.7%): Removed two over-restrictive lines from the Style prompt ("skip trivial nitpicks", "leave acceptable but not perfect code alone") that were suppressing true positives. Simultaneously addressed a methodological discovery (see next subsection).

### Methodological Discovery: Keyword Brittleness

While diagnosing the Style recall drop in v0.3-rc, I found that 3 of 4 "regressed" samples were not actually missed — the agent had caught the bug but paraphrased the description (e.g. "deeply nested" vs the keyword "nesting", "swallows" vs "swallowed"). Only one sample was a genuine prompt-suppression regression. The keyword set was the brittle component, not the model.

I expanded the keyword set uniformly across all 40 samples following a documented protocol:

- Morphological variants of every existing keyword (verb/noun/adjective forms, singular/plural, tenses)
- 1-hop direct synonyms in the context of the bug (e.g. `parameter ↔ argument`, `flag argument ↔ flag parameter`)
- Acronym ↔ full form (e.g. `DoS ↔ denial of service`)
- **Not added**: domain reasoning chains, concept reframings, or anything driven by reading predicted outputs (to avoid reverse-engineering the test)

Both multi-agent and baseline were then re-scored against the expanded ground truth. Interestingly, the baseline F1 didn't change — single-LLM output already used canonical terminology that matched the original keywords. The keyword expansion fixed measurement bias on the multi-agent side, where output paraphrasing was more common.

### Caveats (Read Before Citing These Numbers)

- **n = 40, hand-crafted by the author.** Selection bias is real. Numbers do not extrapolate to real-world repositories without a larger, sourced eval set.
- **RAG is bypassed in this evaluation.** Samples are isolated code snippets without a surrounding repository to index. RAG effectiveness needs a different eval design (multi-file samples with a populated vector store).
- **Keyword matching remains an imperfect scoring function.** Even after expansion, paraphrased true positives can still be missed. Future work: semantic similarity matching via embeddings to replace literal keyword checks.

---

## Project Layout

```
backend/
├── app/
│   ├── agents/       LangGraph nodes (security/performance/style/synthesis) + prompts
│   ├── api/v1/       FastAPI routers (reviews, repositories, webhooks, metrics, ws)
│   ├── rag/          AST chunker + embeddings (DashScope) + pgvector cosine retriever
│   ├── platform/     Git platform adapters (GitHub implemented; GitLab/Gitee planned — see Roadmap)
│   ├── tasks/        ARQ tasks (review pipeline + indexing)
│   └── models/       SQLAlchemy ORM
├── scripts/
│   ├── run_eval.py   Multi-agent vs baseline comparison runner
│   ├── eval_data/    40 hand-crafted samples (security/performance/style)
│   └── eval_results/ Iteration history (v0.2 / v0.3-rc / Path X)
└── tests/

frontend/
├── src/
│   ├── pages/        Dashboard, Repositories, ReviewDetail, Metrics
│   ├── components/   shadcn/ui + Monaco
│   └── lib/api.ts    Axios client + WS helpers
```

---

## Status & Roadmap

**Shipped (current: v0.5.2):** multi-agent parallel review + RAG (pgvector / DashScope embeddings) · GitHub PR webhook → status check + review comment · AutoFix agent (unified-diff patches validated with `ast.parse` / `node --check` — no code execution yet) · full Docker Compose stack · **public HTTPS deployment with a live demo at [tantai.xyz](https://tantai.xyz)**.

**Planned:**

- **GitLab / Gitee adapters** — the `GitPlatformAdapter` abstraction is in place; only GitHub is implemented today. Adding a platform means implementing one adapter, no changes to the review pipeline.
- **CI** — GitHub Actions running the full test suite against a pgvector service (the integration tests currently require a local Postgres and skip without one).
- **Semantic eval scorer** — embedding similarity to replace the literal keyword check, plus multi-file eval samples to actually measure RAG contribution.
- **Pre-classification router** — a router node before the agent fan-out that only activates the relevant agents per file/diff, further reducing cross-category prediction volume.
- **i18n** — English/Chinese UI toggle (the UI is currently Chinese-first).

---

## License

MIT
