# CodeSentinel Demo 剧本（v0.5.1）

照着走，别现场即兴。固定样本：[`docs/demo-samples/buggy_payment.py`](./demo-samples/buggy_payment.py)。

主线走 **webhook 实战**；外部不可控时切 **paste 模式兜底**（不依赖 GitHub、不碰 embedding，最稳）。

---

## 0. 开演前 5 分钟预检（务必全绿再开始）

| 检查 | 命令 / 动作 | 期望 |
|---|---|---|
| 后端活着 | `curl http://<公网IP>:8000/api/v1/health` | `{"status":"ok"}` |
| 前端打得开 | 浏览器开 `http://<公网IP>:5173` | NewReview 页正常渲染 |
| 前端 bundle 烘焙的是公网 IP | DevTools Network 看 API 请求目标 | 打到 `<公网IP>:8000`，不是 localhost |
| embedding / RAG（v0.5.1 已修，生产可用） | 见下方「embedding / RAG 说明」 | 成功取回同仓 RAG 上下文 |
| 目标仓库已注册 | Repositories 页能看到它 | URL 完全等于 `https://github.com/<owner>/<repo>` |
| 容器都健康 | `docker compose -f docker-compose.prod.yml ps` | backend/worker/postgres/redis 全 Up/healthy |
| backup 链接就绪 | 见第 4 节 | 预跑好的 review 详情页 URL 已存 |

### embedding / RAG 说明（webhook 模式）
已注册仓库走 webhook 审查时，`retrieve_context` 用 **PR diff 作 query** 打一次 DashScope `text-embedding-v3`，取回**同仓最相关的代码 chunk** 作为 RAG 上下文注入各 Agent（review_task.py:50-54）。**v0.5.1 起 embedding provider 已从 DeepSeek 切到 DashScope，生产真正生效**（此前误用 DeepSeek 凭据调阿里模型必 404，已修）。
> **demo 卖点核心**：Demonstration 仓库的 `main` 已种入 `src/payments/` 规范源码并索引（11 个 code_chunks）。审 buggy PR 时，RAG 会召回这些"正确实现"作对照——例如审到 `get_user_orders` 的 SQL 注入时，带出仓库自己的参数化 `OrderRepository`。讲解时可强调「不只指出问题，还引用了仓库已有的安全写法」。
> embedding 仍是**增强项**：万一失败，`retrieve_context` 优雅降级返 `""`，审查照常（PR diff 已含待审代码）。paste 模式 `repository_id=None` 从不调 embedding。
> 前提：RAG 要有效，目标仓库**默认分支**须有可索引源码且 `code_chunks` 非空（注意 `index_task` 的 `_SKIP_DIRS` 含 `docs`，样本别放 `docs/`）。

---

## 1. 主线 Demo：真实 PR → 自动审查 → 回写

### 一次性准备（演示前就做好，别占用演示时间）
> **目标仓库用专门新建的公开仓库**（如 `Demonstration`），别用你的主仓/私有仓：token 只需 `public_repo` 最小权限，泄露爆炸半径最小；公开仓 worker 拉 diff 也无需额外授权。
1. **注册仓库**：前端 `/repositories` → 填
   - platform: `github`
   - url: `https://github.com/<owner>/<repo>`　**不带 `.git` 后缀**
     （webhook 按 `html_url` 精确匹配：`.git` 后缀或大小写不一致会导致被 ignore；尾斜杠会被注册端 `rstrip("/")` 自动剥除，无碍）
   - **仓库主语言**：webhook 模式 `language` 取自 GitHub 识别的仓库主语言（默认 python）。demo 建议用 GitHub 识别为 Python 的仓库，免得 language 标错影响审查
   - webhook_secret: 与 `.env` 的 `GITHUB_WEBHOOK_SECRET` 一致
2. **配 GitHub Webhook**：仓库 Settings → Webhooks → Add：
   - Payload URL：`http://<公网IP>:8000/api/v1/webhooks/github`（ngrok 阶段用 ngrok 域名）
   - Content type：`application/json`
   - Secret：同上
   - 事件：**只勾 Pull requests**
3. **准备 buggy 分支**：把 `buggy_payment.py` 放进目标仓库一个新分支，但**先不开 PR**（演示时现场开）。
   > **Demonstration 仓库已就绪（2026-05-29）**：`main` 已有 `src/payments/` 规范源码并完成索引（11 chunks，供 RAG 召回）；`demo-buggy` 分支 + PR #1 已存在。**要刷新一次演示**，无需新开 PR——直接在 PR #1 页面 `Close → Reopen`（徽章走一轮 Open→Closed→Open）即触发 `reopened` webhook 重审，几秒后刷出新评论。

### 现场动作（约 2 分钟）
1. 在 GitHub 现场 **开 PR**（buggy 分支 → 主分支）。
2. 几秒内 PR 的 commit 上出现 **黄色 pending** 状态：`CodeSentinel review in progress…`
3. （可选加分）打开 CodeSentinel 该 review 的详情页，WebSocket 实时流式输出三个 Agent 的审查过程 + synthesis 报告。
4. 审查完成后：
   - commit 状态变 **failure**（因为样本含 critical），描述带 issue 计数
   - PR 下出现 **CodeSentinel Review 评论**：critical/warning/suggestion 计数 + synthesis 报告
5. 对着评论讲：哪条是 SQL 注入、哪条是 O(n²)、哪条是 style，呼应「多 Agent 并行 + 综合」的卖点。

---

## 2. Paste 模式兜底（不依赖 GitHub / 不碰 embedding）

外网 GitHub 抖动或 webhook 不通时切这条，照样完整展示审查能力：
1. 前端首页 `/`（NewReview） → 粘贴 `buggy_payment.py` 全文 → 选 language `python` → 提交
   （单次上限 50000 字符，样本远小于此）
2. 自动跳转 review 详情页，WebSocket 流式输出审查过程
3. 终态展示 issue 列表 + synthesis 报告（与 webhook 评论内容同源）
> paste 模式 `repository_id=None` → 无 RAG 上下文、不调 embedding、不回写 GitHub，是最不依赖外部的演示路径。

---

## 3. 预期产出（对应 `buggy_payment.py`，讲解时照此对账）

| 维度 | 代码位置 | 期望命中 | severity |
|---|---|---|---|
| SQL 注入 | `get_user_orders` 拼接 `uid` | 必中 | critical |
| 硬编码密钥 | `API_SECRET` / `charge` 返回里带 secret | 必中 | critical |
| `eval` 用户输入 | `run_rule` | 高概率 | critical |
| O(n²) 成员判断 | `find_duplicates` 的 `x in seen` | 高概率 | warning |
| 循环内字符串拼接 | `build_report` 的 `s = s + ...` | 中概率 | warning/suggestion |
| 裸 except 吞异常 | `charge` 的 `except:` | 高概率 | suggestion |
| 缺类型注解 / 命名差 | 全文 | 中概率 | suggestion |

> **数量会浮动,别赌固定数字**（LLM 固有随机性）：实测总数在 **8~11** 之间（v0.5.0 基线 8 = 3 critical/2 warning/3 suggestion；2026-05-29 RAG 启用后实测 11 = 3 critical/3 warning/5 suggestion）。**critical 稳定 ≥3**（注入/密钥/eval 几乎必现）。逐条措辞不保证,讲解锚定必现的 critical,不要在面试现场报死总数。

---

## 4. 风险与 Backup（live demo 三大不可控）

| 风险 | 兜底 |
|---|---|
| DeepSeek 慢/失败 | 预先跑好一个 review，存好 **详情页 URL**：`http://<公网IP>:5173/review/<reviewId>`，直接打开讲结果 |
| GitHub API 限流 / 网络 | 切 **paste 模式**（第 2 节） |
| 效果抖动 | 只用**固定样本**，不现场改代码；讲解锚定必现的 critical |
| webhook 不触发 | 看 GitHub → 仓库 Settings → Webhooks → **Recent Deliveries**，能看请求/响应/重投 |

**backup 详情页 URL（演示前填好）**：`__________________________`

---

## 5. 排查速查（出问题按这个顺序看）

1. **GitHub Recent Deliveries**：webhook 到底发出去没？响应码是几？
   - 401 → 验签失败：`GITHUB_WEBHOOK_SECRET` 与注册时 `webhook_secret`、GitHub 配置三者不一致
   - 200 `{"status":"ignored","reason":"repository not registered"}` → 仓库没注册或 URL 没精确匹配（`.git` 后缀 / 大小写；尾斜杠已被注册端 rstrip，不影响）
   - 200 `{"status":"ignored","reason":"action=..."}` → 不是 opened/synchronize/reopened，正常
2. **worker 日志**：`docker compose -f docker-compose.prod.yml logs -f worker`
   - 拉 diff 失败 → `GITHUB_TOKEN` scopes 不够（公开仓库 `public_repo`，私有仓库 `repo`）
   - embedding 报错 → 见第 0 节，或切 paste 模式
3. **pending 状态没出现** → webhook handler 里 `set_commit_status` 是尽力而为（失败只 warning 不阻塞），看 backend 日志 `github_status_pending_failed`；多半还是 token scope（缺 `repo:status`）
4. **前端 API 全跨域失败** → `CORS_ORIGINS` 没含前端实际 origin（带端口、不带尾斜杠），或前端 bundle 烘焙了错的 `PUBLIC_API_URL`（需重 build）
