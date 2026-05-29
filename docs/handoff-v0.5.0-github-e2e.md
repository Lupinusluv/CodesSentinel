# v0.5.0 工作交接 — GitHub 端到端上线（裸 IP 部署 + webhook 实战）

**前提**：v0.4.3 已 ship（tag v0.4.3 在 main）。本版本在新分支 `feat/v0.5.0-deploy` 上做。
**部署方案**：`http://公网IP:8000`，不买域名、不配 SSL（X 方案，先跑起来）。

---

## 核心认知（先读这段，否则方向会跑偏）

**闭环代码已经全部写好了。** 经代码勘察确认，下面这条链路在代码层面是完整的：

```
GitHub PR 事件
  → webhooks.py        验签 → 事件过滤 → 设 pending status → 写 Review → 入队 ARQ（202，<100ms）
  → review_task.py     Worker 拉 PR diff → RAG 上下文 → 多 Agent 并行审查 → 去重落库
  → _maybe_notify_github  回写 commit Status Check（critical>0 → failure，否则 success）
                          + 在 PR 下发布格式化 Markdown 评论
```

所以 **v0.5.0 不是"写功能"，是"让已写好的代码在真实世界第一次跑通"**。
工作量集中在三件事：**① 部署（含先修两个部署 blocker）② 把真实 GitHub webhook 接上并联调 ③ 补回写路径的测试 + 准备 demo 剧本**。

涉及文件（已勘察，无需重写，只需让它们跑起来）：
- `backend/app/api/v1/webhooks.py` — webhook 入口，完整
- `backend/app/tasks/review_task.py` — `_fetch_pr_diff` / `_maybe_notify_github` / `_format_pr_comment`，完整
- `backend/app/platform/adapters/github.py` — `get_pr_diff` / `post_review_comment` / `set_commit_status`，完整

---

## 已就绪 vs 缺口

| 环节 | 代码状态 | 真实世界缺口 |
|---|---|---|
| Webhook 验签/过滤/入队 | ✅ 完整 | 需 `.env` 配 `github_webhook_secret` |
| Worker 拉 diff + 审查 | ✅ 完整 | 需 `github_token`（含正确 scopes） |
| 回写 status + PR 评论 | ✅ 完整 | **零测试覆盖**（见 Phase 0） |
| 仓库注册 | ✅ Repositories 页可注册 | webhook 对**未注册仓库直接 ignore**（webhooks.py:123），demo 前必须先注册 |
| 部署编排 | ⚠️ 仅 dev compose | 需 prod 化（见 blocker 2、3） |
| CORS | ❌ 生产环境锁死 | **部署 blocker 1，必修** |

---

## 部署 Blocker（不修则部署即挂，必须在 Phase 1 最先处理）

### Blocker 1：生产 CORS 是空白名单 —— 前端全部 API 被浏览器拦
`backend/main.py:38`：
```python
allow_origins=["http://localhost:5173"] if settings.is_dev else []
```
`app_env=production` 时 `is_dev=False` → `allow_origins=[]` → 浏览器拦掉前端所有跨域请求。

**修法**（`config.py` 加可配置项，main.py 读它）：
```python
# config.py
cors_origins: str = ""   # 逗号分隔，如 "http://公网IP:5173"

@property
def cors_origin_list(self) -> list[str]:
    if self.is_dev:
        return ["http://localhost:5173"]
    return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
```
```python
# main.py
allow_origins=settings.cors_origin_list,
```
`.env` 里写 `CORS_ORIGINS=http://公网IP:5173`（前端实际访问的 origin，注意带端口、不带尾斜杠）。

### Blocker 2：前端 API/WS 地址是 build 时烘焙的
`frontend/src/lib/api.ts:4`：`import.meta.env.VITE_API_URL ?? 'http://localhost:8000'`
Vite 把 `VITE_*` 在**构建时**写死进产物。当前 dev compose 给的是 `localhost`。部署必须用公网 IP 重新构建：
```
VITE_API_URL=http://公网IP:8000
VITE_WS_URL=ws://公网IP:8000
```
（WS 用 `ws://` 不是 `wss://`，因为无 SSL。）

### Blocker 3：docker-compose.yml 是 dev 编排，不能直接当生产用
现状：`backend`/`frontend` 都挂源码 volume + 跑 dev server，frontend 写死 `localhost`。
需新增 `docker-compose.prod.yml`（override）：
- 去掉源码 volume 挂载（用镜像内代码）
- frontend 改为 build 静态产物 + 静态服务（或保留 vite preview，端口对外）并注入公网 IP 的 `VITE_*`
- backend `command` 用生产模式（去掉 `--reload`，确认 entrypoint 仍跑 `alembic upgrade head`）
- 注意：`worker` `depends_on: backend service_healthy`，healthcheck 打 `/api/v1/health`（已确认该路由存在，路径正确，无需改）

> 提醒：dev 下后端是 `uvicorn --reload` 直接跑，compose 的 `backend`/`worker` 服务**很可能从没用 compose 真正启动过**。Phase 1 第一次用 compose 起全栈时，留意 build / 迁移 / healthcheck 这几步首次暴露的问题。

---

## Phase 0：先补回写路径的集成测试（建议我/测试会话先做，再碰真实仓库）

**为什么先做**：`_maybe_notify_github` 会**写真实 GitHub PR**（status check + 评论），而它目前**零测试**。不想靠"刷真实 PR"来发现状态逻辑写反（比如 critical 判定、failed 路径）。先把逻辑用 mock 锁死，再拿真仓库验证。

**怎么 mock**：用 httpx 自带 `MockTransport`（**零新依赖**，requirements 里只有 httpx 0.28.1，没有 respx），拦截 `api.github.com` 请求。

**测试清单**（建议放 `backend/tests/integration/test_webhook_flow.py` + `test_github_notify.py`）：
1. **验签**：有效签名 → 202；无效签名 → 401；缺 `X-Hub-Signature-256` 且配了 secret → 401
2. **事件过滤**：非 `pull_request` 事件 → ignored；action 不在 `{opened,synchronize,reopened}` → ignored；未注册仓库 → ignored（不入队）
3. **`_maybe_notify_github` 状态逻辑**：
   - issues 含 critical → status `failure`
   - issues 无 critical → status `success`
   - 无 issues → `success` + desc "No issues found"
   - `failed=True` → status `failure`，**不发**评论
   - paste 模式（`head_sha=None`）→ 静默跳过，不调 GitHub
4. **`_format_pr_comment`**：critical/warning/suggestion 计数正确，含 header 和 footer

**验收**：新测试通过 + 原 74 测试（50 单元 + 24 集成）不回归。

---

## Phase 1：部署（裸 IP，X 方案）

1. 服务器准备：装 Docker + Docker Compose，开放安全组/防火墙 **8000**（后端）和前端端口（5173 或你选的）入站
2. 修 Blocker 1（CORS 可配置）
3. 写 `docker-compose.prod.yml`（Blocker 3）
4. 前端用公网 IP 注入 `VITE_*` 构建（Blocker 2）
5. 配 `.env`（见下方密钥清单）
6. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
7. entrypoint 自动 `alembic upgrade head`，确认迁移成功、`/api/v1/health` 返回 200

**`.env` 密钥清单**：
| 变量 | 值 / 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | 主 LLM |
| `DATABASE_URL` | compose 内 `postgresql+asyncpg://codessentinel:codessentinel@postgres:5432/codessentinel` |
| `REDIS_URL` | `redis://redis:6379/0` |
| `GITHUB_TOKEN` | PAT，scopes 见下 |
| `GITHUB_WEBHOOK_SECRET` | 自定义随机串，需和 GitHub webhook 配置一致 |
| `APP_ENV` | `production` |
| `CORS_ORIGINS` | `http://公网IP:前端端口` |

**`GITHUB_TOKEN` 所需 scopes**（经代码确认需要的 3 个 GitHub 操作）：
- `get_pr_diff`（读 PR）、`set_commit_status`（写 commit status）、`post_review_comment`（在 PR issue 下评论）
- 经典 PAT：公开仓库勾 `public_repo`；私有仓库勾 `repo`（含 `repo:status`）即可覆盖以上三者

---

## Phase 2：webhook 实战联调

> **强烈建议先用 ngrok 在本地把整条链路打通，再上裸机。** 裸机盲调 webhook 很痛苦；ngrok（`ngrok http 8000`）能让你在本地完整复现 GitHub → 后端这一跳。

联调步骤：
1. 在 CodeSentinel 前端 Repositories 页**注册目标仓库**（否则 webhook 直接 ignore）
2. GitHub 仓库 → Settings → Webhooks → Add webhook：
   - Payload URL：`http://公网IP:8000/api/v1/webhooks/github`（ngrok 阶段用 ngrok 域名）
   - Content type：`application/json`
   - Secret：填 `GITHUB_WEBHOOK_SECRET` 的值
   - 事件：只勾 **Pull requests**
3. 核对 `GITHUB_TOKEN` scopes
4. 开一个测试 PR，期望观察到：
   - 几乎立刻：PR 的 commit 出现 **pending** status（"CodeSentinel review in progress…"）
   - 审查完成后：status 变 **success/failure**（按 critical 数）
   - PR 下出现 **CodeSentinel Review 评论**（issue 计数 + synthesis 报告）
5. 出问题先看 GitHub webhook 的 "Recent Deliveries"（能看到请求/响应/重投），再看 worker 日志

---

## Phase 3：demo 剧本

**主线 demo**：开 buggy PR → 实时看 commit status 转 pending → 前端 WS 流式输出审查过程 → PR 收到评论 + status 终态。

**风险与 fallback**（live demo 三大不可控因素）：
- **LLM 延迟/抖动**：DeepSeek 偶发慢或失败 → 准备一个**预先跑好**的 review 详情页 URL 作 backup
- **GitHub API 限流/网络**：→ 准备 **paste 模式** demo（前端直接贴代码，不依赖 GitHub），作为完全不依赖外网 GitHub 的兜底
- **demo 效果不稳定**：固定一个**小而有代表性的 buggy PR**（已知能稳定产出 critical + warning + suggestion 各若干），别现场即兴写代码

**脚本化建议**：把 buggy 代码片段、PR 创建步骤、预期输出、backup 链接都写进一个 `docs/demo-script.md`，演示时照着走。

---

## 验收（架构/测试会话做）

1. **端到端真实链路**：真实 PR 触发 → pending status → 审查 → status 终态正确 + PR 评论正确
2. **测试基线**：Phase 0 新增 webhook/notify 集成测试通过；原 74 测试不回归；`tsc --noEmit` 零错误
3. **部署可复现**：`docker compose -f ... -f docker-compose.prod.yml up` 一条命令起全栈，迁移自动跑通

---

## 不在本轮范围

- GitLab / Gitee 适配器（webhooks.py 已占位返回 501，接口结构就绪，适配器实现留后）
- HTTPS / 域名（明确选裸 IP）
- i18n（v0.4.4，独立分支，零风险，可在 v0.5.x 任意空档插入）
- 业务文本（LLM 输出）国际化

---

## 版本切片建议（供"架构和测试"拍板）

v0.5.0 体量偏大，可考虑切成两刀，降低单次风险：
- **v0.4.5**（先）：Phase 0 测试硬化 —— 纯后端、低风险、不碰部署，把回写逻辑锁死
- **v0.5.0**（后）：Phase 1-3 部署 + 实战 + demo

这样真正拿真实仓库联调时，回写逻辑已有测试背书。如果不想多开一个版本号，则把 Phase 0 作为 v0.5.0 的第一个 commit。

---

## 工程量估计（粗）

| 阶段 | 估计 | 风险 |
|---|---|---|
| Phase 0 测试 | 半天 | 低 |
| Phase 1 部署 + 修 3 blocker | 1 天（含第一次 compose 起全栈踩坑） | 中 |
| Phase 2 webhook 联调 | 半天~1 天（ngrok 先行能压缩） | 中高（外部依赖） |
| Phase 3 demo 剧本 | 半天 | 低 |
