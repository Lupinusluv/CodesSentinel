# 全仓代码审计 — 2026-06-03（架构和测试）

> 目标：把 ③「代码整体审计」从"70 分（仅审计了高价值子集）"推进到一份**逐模块的完整质量台账**，
> 覆盖上一轮没深审的 API 层、前端全部、task 内部、chunker、models、eval。
> 本文档只做**诊断 + 排序**，不含代码改动。修复由用户拍板后另行执行。

读取范围：`backend/app` 全部 51 个 .py + `backend/scripts/run_eval.py` + `frontend/src` 全部 16 个 .ts/.tsx + `main.py` + CI/配置。

---

## 0. 总体结论

代码**地基扎实**，不是"勉强能跑"的级别：task/graph 副作用边界、operator.add reducer、HMAC 验签、from_dsn、幂等写入、WS 竞态处理这些"容易翻车"的点都处理得到位且有注释解释「为什么」。上一轮 P0/P1（去重/CI/验签 fail-closed/parse 信号/black）也确实落地了。

**但有一类系统性短板**：**信号/能力在链路末端断掉**——后端做对了，前端或边缘脚本没接上。最典型的就是 B5 的 `parse_failures`：后端发了、type 声明了，前端 `useReview` 直接忽略。这类"半截子"问题是当前从 70→85 的主要扣分项，且多数改动量很小。

按模块打分（10 分制，"可用 + 可面试"双视角）：

| 模块 | 分数 | 一句话 |
|------|------|--------|
| `agents/` (graph/state/三 agent/synthesis/prompts) | 9 | 最强的一块，lane 纪律 + reducer 处理都很讲究 |
| `agents/autofix_agent` + `tasks/autofix_task` | 8.5 | 分组/final patch/幂等都对，逻辑密度高 |
| `tasks/review_task` | 8.5 | 事件路由稳，parse_failures 已穿透到 done |
| `tasks/index_task` | 7.5 | 逻辑对，但串行 embedding + GitHub 硬编码 |
| `rag/` (chunker/retriever/embeddings) | 8 | AST 分块干净；检索是粗粒度 MVP |
| `api/v1/` (reviews/patches/webhooks/repositories) | 8 | 入参校验齐全；少量过度取数 + 平台一致性缺口 |
| `api/v1/metrics` | 6.5 | 分布查询漏了 status 过滤；import 乱序；死端点 |
| `core/` (config/dependencies/logging) | 9 | fail-closed + from_dsn + 单例都对 |
| `platform/` | 7 | github 适配器干净；gitlab/gitee 是空文件 |
| `sandbox/` | 8.5 | 只解析不执行，边界清楚，node 缺失降级 |
| `models/` | 9 | 约束/级联/枚举都规范 |
| **前端 `useReview` / `PatchPanel`** | 7 | 功能在，但 WS/异常/parse_failures 收尾不全 |
| 前端其余页面/组件 | 8 | 干净，符合规范 |
| `scripts/run_eval` | 8 | 增量落盘 + 复用 baseline 很专业；ReviewState 漏 key |

---

## 1. P1 — 应当修（影响正确性/可用性/可信度）

### M1. `parse_failures` 信号到前端就断了（B5 半成品）❗最该补
- 链路：`*_agent` 上报 → `state` 累加 → `review_task` 写进 `done` 事件 → `types.ts` 已声明 `parse_failures?: string[]`。
- **断点**：`frontend/src/hooks/useReview.ts` 的 `done` 分支只 `reviewApi.get(id)`，**完全没读 `parse_failures`**。
- 后果：整条 B5 是为了"某类问题被 LLM 输出解析失败而静默吞掉"时给用户**可见信号**；现在信号到了浏览器却没人显示，等于白做最后一跳。
- 建议：done 时若 `parse_failures` 非空，在结果区顶部挂一条 warning（如"⚠️ security 分析结果解析失败，本次可能漏报安全问题"）。改动 ~10 行。

### M2. 前端可注册 gitlab/gitee，但后端只能索引 GitHub（能力一致性缺口）
- `Repositories.tsx` 三个平台都能选并注册；`Platform` 枚举也三个都有；`create_repository` 照单全收。
- 但 `index_task.py` **硬编码** `GitHubAdapter` + `api.github.com`；`webhooks` 的 gitlab/gitee 直接 501。
- 后果：注册一个 GitLab/Gitee 仓库 → 点"触发索引" → task 拿 GitLab URL 去打 GitHub API，404 静默失败，`indexed_at` 永远不更新，用户不知道为什么。UI 承诺了后端兑现不了的东西。
- 我们已决策"适配器只标 roadmap"，所以**正确做法是收 UI**：gitlab/gitee 选项置灰 + 标"roadmap"，或注册时前端拦截提示。改动小，且消除一个 demo 翻车点。

### M3. WebSocket 异常关闭 → 前端永久卡在 "审查中…"
- `useReview.ts` 有 `onmessage` / `onerror`，**没有 `onclose`**。
- 若 socket 在收到终态 `done`/`error` 前被关闭（worker 崩、后端重启、网络抖动、Nginx 超时断流），phase 停在 `streaming`，转圈圈永不结束，也不报错。
- 建议：加 `ws.onclose`，若关闭时 phase 仍为 streaming/submitting，则切到 error 并提示"连接中断"。

### M4. `done` 后的 `reviewApi.get` 无 catch
- `useReview.ts`：`reviewApi.get(id).then(res => setPhase('done'))` 没有 `.catch`。该 GET 偶发失败时，phase 永不进入 done，UI 卡住。
- 建议：加 `.catch` 兜底（至少切 error）。和 M3 是同一类"末端鲁棒性"。

---

## 2. P2 — 建议修（质量/一致性/轻度性能，不紧急）

### L1. `metrics_summary` 分布查询漏了 `status==done` 过滤
- headline（total_reviews/issues/avg）都过滤了 `done`，但 `issues_by_category/severity` 的分组查询**没有任何 status 过滤**。当前因为 issue 只在 done 路径写库，实际数据一致；但语义上 headline 与分布可在未来分叉。建议补同样的 join/过滤，或注释说明依赖。

### L2. Dashboard/list 接口过度取数
- `GET /reviews` 的 `_to_response` 对 50 条记录**每条都带 `source_code` 全文 + `report_text` 全文**。Dashboard 只用 issues 算 severity 计数，根本不渲染源码/报告。50 条 PR diff 全文一次性过网，payload 偏重。
- 建议：list 用精简 schema（不含 source_code/report_text），详情页再单独拉。

### L3. `metrics.py` 杂项
- import 分组乱序（sqlalchemy/app.* 在 fastapi/pydantic 之前），与全仓"stdlib → 第三方 → 本地"约定不符；black 不排序 import，CI 也没有 isort/ruff 兜底——**全仓 import 顺序无机器保证**。
- `GET /metrics/issues` 无 `response_model`，且前端 `metricsApi` 只调 `/metrics`，是个死端点。

### L4. `gitlab.py` / `gitee.py` 是 0 字节空文件
- 作为 roadmap 占位，空文件读起来像"忘删的残骸"。建议至少放模块 docstring + `class XxxAdapter(GitPlatformAdapter)` 抛 `NotImplementedError` 的骨架，让"未实现"成为显式声明。

### L5. `run_eval.py` 的 `ReviewState` 漏了 `parse_failures` 键
- B5 给 `ReviewState` 加了 `parse_failures` 后，eval 的 `run_multi_agent` 构造 state 时没同步加该键（reducer 通道默认空、大概率不崩，但属隐性不一致，升级 langgraph 时易踩）。建议补齐，与 `review_task` 对齐。

### L6. `index_task` embedding 串行批次
- 200 文件的所有 chunk 按每 10 条**串行** `await embed_texts`，索引大仓时往返累加偏慢（仅影响索引任务，不在审查热路径）。可用 `asyncio.gather` + 信号量并发。**此项上一轮已决策"最低优先/可砍"，仅记录。**

### L7. `retrieve_context` 检索粒度粗
- 把整段 diff/源码 `[:4000]` 作为**单一** query 向量去检索，对多文件 diff 偏粗。MVP 可接受，记录为已知局限。

---

## 3. 做得好的地方（台账正向项，面试可讲）

- **副作用边界**：所有图节点严格只读写 state，DB IO 全在 task 层；`autofix_agent` / `review_task` 双向对称，注释明确。
- **reducer 陷阱处理**：`synthesis_node` 特意只返回 `report_text` 不返回 issues，并注释解释"否则 operator.add 会二次追加导致写库翻倍"——这是真正踩过坑才会写的注释。
- **安全**：HMAC `compare_digest` 常量时间比较；生产缺 webhook secret 启动即硬失败（fail-closed）；`from_dsn` 保住 redis 密码/TLS/db 索引。
- **幂等**：index 先删后插；autofix trigger 同步 DELETE 旧 patch + task 内再 DELETE 双保险 + 重置 `fixed`。
- **WS 竞态**：晚连接的双重 done/failed 检查 + progress hash 追赶，覆盖了"连接晚于事件"的经典竞态。
- **prompt lane 纪律**：三个 agent 都有明确 in-lane/out-of-lane + 反 lane-bleeding 措辞，是多 agent 相比单 LLM 的核心卖点支撑。
- **eval 工程性**：增量原子落盘（tmp+rename 抗崩）、`--reuse-baseline` 省 token、baseline 指标始终按当前 expected 重算。

---

## 4. 修复优先级建议（待用户拍板）

**第一批（P1，全是小改动，直接抬"可用"分）**
1. M1 前端显示 `parse_failures` warning
2. M3 + M4 WebSocket onclose / get catch 兜底
3. M2 收 UI：gitlab/gitee 置灰标 roadmap

**第二批（P2，质量打磨）**
4. L2 list 接口精简 schema（payload 优化，最有体感）
5. L1 metrics 分布加 status 过滤
6. L4 + L5 空适配器骨架 + eval state 对齐
7. L3 引入 ruff（顺带管 import 排序）并加进 CI

**记录不改（已决策/MVP 局限）**：L6 串行 embedding、L7 检索粒度。

> 结论：补完第一批（4 个 P1，预计都是小改动）后，③ 可从"70 分targeted"实质上到 **82–85**；
> 第二批补完接近 88。没有发现需要返工的架构性错误，主要是"末端收尾"和"一致性"层面的债。
