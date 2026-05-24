# CodeSentinel 架构设计文档

> 本文档记录项目架构决策、数据流设计、模块职责划分及 Git 工作流。是编码阶段的设计基准，有重大变更时同步更新。

---

## 一、产品定位与用户场景

### 目标用户

独立开发者或小型团队，使用 GitHub / GitLab / Gitee 托管代码，缺乏系统性 Code Review 流程。

### 典型使用场景

**场景一：Webhook 自动接入（完整体验）**

以一个开发微信小程序的独立开发者"小王"为例：

1. 在 CodeSentinel Dashboard 注册 GitHub 仓库，获得 Webhook URL + Secret，粘贴到 GitHub 仓库设置。一次性配置，后续全自动。

2. 小王日常提 PR，包含如下有问题的代码：

   ```javascript
   const API_KEY = "sk-1234567890abcdef"  // 硬编码密钥

   async function getOrderList(userId) {
     const orders = []
     const result = await db.collection('orders').where({ userId }).get()
     for (let i = 0; i < result.data.length; i++) {
       orders.push(result.data[i])
       this.setData({ orders })            // 循环内调 setData，触发重渲染
     }
     return orders
   }
   ```

3. GitHub 推 Webhook，CodeSentinel 后台自动启动三路 Agent 并行审查。

4. 小王回来，PR 页面出现 CodeSentinel Bot 评论：

   ```
   🔴 Critical (1)
     payment.js:1 — 硬编码 API 密钥暴露在代码中，建议改为环境变量

   🟡 Warning (2)
     payment.js:11 — setData() 在循环内调用，每次触发小程序重渲染
     payment.js:7  — 数据库查询缺少错误处理，网络失败时静默报错

   💡 Suggestion (3)
     utils.js:34 — 函数圈复杂度过高（12），建议拆分
     payment.js:4 — 建议补充 JSDoc 参数说明
     payment.js:9 — 可简化为 const orders = result.data

   Status Check: ⚠️ 1 critical issue, please fix before merge
   ```

5. 小王进入 Dashboard ReviewDetail 页面，Monaco Editor 高亮问题行，点击「自动修复」：

   ```diff
   - const API_KEY = "sk-1234567890abcdef"
   + const API_KEY = process.env.API_KEY
   ```

   沙箱验证通过后，小王 apply patch，Status Check 变为 ✅。

**场景二：Web 界面手动粘贴（MVP 演示 / 面试场景）**

无需配置 Webhook。进入 Dashboard，选语言，粘贴代码片段，点击「开始审查」。右侧实时流式输出审查结果（逐 token 显示）。30 秒内出结果，适合面试现场演示。

---

## 二、API 路由设计

### RESTful 接口（`/api/v1/`）

```
POST   /api/v1/reviews                  创建审查（接收代码片段或 PR 信息）
GET    /api/v1/reviews                  审查历史列表
GET    /api/v1/reviews/{review_id}      单次审查详情（含 issues）

POST   /api/v1/repositories            注册仓库
GET    /api/v1/repositories            仓库列表
DELETE /api/v1/repositories/{repo_id}  删除仓库

POST   /api/v1/webhooks/github         接收 GitHub PR 事件
POST   /api/v1/webhooks/gitlab         接收 GitLab MR 事件
POST   /api/v1/webhooks/gitee          接收 Gitee PR 事件

GET    /api/v1/metrics                  统计汇总（审查数、平均耗时、修复率）
GET    /api/v1/metrics/issues           问题类型分布（security/perf/style 各占比）
```

### WebSocket

```
WS /ws/{review_id}                      订阅指定审查的实时 token 流
```

### 设计决策说明

**Webhook 按平台拆分为三个路由**，而不是 `/webhooks/{platform}` 统一路由。原因：各平台 HMAC 验签逻辑不同（Header 名、算法、密钥均不同），分开路由各自处理，安全边界清晰，不容易在统一路由中写出判断漏洞。

**POST /reviews 立即返回 `review_id`**，状态为 `pending`，不等待 LLM 执行结果。前端拿到 `review_id` 后立刻建立 WebSocket 连接订阅进度。

---

## 三、数据流设计

### 主链路：Webhook 触发（异步）

```
Git 平台
  │  PR/MR 事件 Webhook
  ▼
POST /webhooks/{platform}
  ├─ HMAC 验签（用各平台的 webhook_secret）
  ├─ 写 reviews 表（status = pending）
  └─ 推入 ARQ 任务队列（Redis）
            │
            ▼  Worker 消费
       review_task.py
            ├─ GitPlatformAdapter.get_pr_diff()  拉取 PR diff
            ├─ RAG retriever 检索相关上下文
            │
            ▼
       LangGraph 审查图
            ├─ SecurityAgent   ──┐
            ├─ PerfAgent       ──┼── 并行执行
            ├─ StyleAgent      ──┘
            ▼
       SynthesisAgent  聚合 → 结构化报告（Pydantic）
            │
            ├─ 写 issues 表 + 更新 reviews 表（status = done）
            ├─ Redis Pub/Sub: publish("review:{id}:stream", token)
            └─ GitPlatformAdapter.post_comment()  在 PR 页发评论
                      │
                      ▼
               ws.py 订阅 Redis channel → WebSocket 推前端
```

### 演示链路：手动粘贴（MVP）

```
前端粘贴代码
  │ POST /reviews → 立即返回 review_id (status=pending)
  │
  ├─ 前端建立 WS /ws/{review_id}
  │
  └─ Worker 消费 → LangGraph → 每个 token publish 到 Redis
                                        │
                                   ws.py 订阅 → 前端逐字显示
                                        │
                                   {"type":"done"} 信号
                                        │
                                   前端重新 GET /reviews/{id} 刷新 IssueList
```

### 流式输出的 Redis Pub/Sub 设计

- Channel 命名：`review:{review_id}:stream`
- 消息格式：`{"type": "token", "content": "..."}` / `{"type": "done"}` / `{"type": "error", "message": "..."}`
- Worker 进程和 WebSocket 进程通过 Redis 解耦，支持多个 ws 客户端同时订阅同一审查

---

## 四、后端模块职责

按**依赖方向**组织，下层不依赖上层：

```
core/           零依赖，所有层均可导入
  config.py      Pydantic Settings，读 .env
  logging.py     structlog 初始化
  dependencies.py  FastAPI Depends 工厂（db session、redis 连接）

models/         只依赖 core/
  base.py        Base + TimestampMixin（created_at/updated_at）
  repository.py  Repository ORM（platform, url, webhook_secret, indexed_at）
  review.py      Review ORM（status enum, pr_number, duration_ms, total_issues）
  issue.py       Issue ORM（category, severity, file_path, line_start/end, fixed）

platform/       依赖 core/
  base.py        GitPlatformAdapter 抽象基类（get_pr_diff, post_comment, set_status）
  factory.py     根据 platform 字符串返回对应 adapter 实例
  adapters/
    github.py    PyGithub 实现
    gitlab.py    python-gitlab 实现
    gitee.py     httpx 实现（无官方 SDK，自调 Gitee REST API v5）

rag/            依赖 core/ + models/
  chunker.py     AST 边界分块，按函数/类拆分，返回 CodeChunk 列表
  embeddings.py  Embedding 封装（DeepSeek embedding API）
  indexer.py     遍历仓库文件 → chunker → embeddings → 写 PostgreSQL/pgvector
  retriever.py   混合检索：pgvector 语义搜索（<=> 余弦距离）+ BM25 关键词，结果合并

agents/         依赖 core/ + rag/
  state.py       ReviewState, SecurityIssue, PerfIssue, StyleIssue（Pydantic）
  prompts.py     所有 Agent 的 System Prompt 常量
  security_agent.py    节点函数，只修改 state，无副作用
  performance_agent.py 同上
  style_agent.py       同上
  synthesis_agent.py   聚合三路结果，生成最终 ReviewReport
  autofix_agent.py     生成修复 Patch（可选触发）
  graph.py       组装 LangGraph 图：定义节点、并行边、条件边

tasks/          最高层，依赖所有模块
  review_task.py  消费队列，调 platform adapter 拉 diff，执行图，写 DB，publish Redis
  index_task.py   消费队列，调 RAG indexer 建索引
  worker.py       ARQ WorkerSettings，注册任务函数列表

api/v1/         路由层（薄），不写业务逻辑
  reviews.py      验参 → 写 DB → 推队列 → 返回 review_id
  repositories.py CRUD
  webhooks.py     验签 → 写 DB → 推队列
  metrics.py      聚合 SQL 查询
  ws.py           WebSocket 连接管理 + 订阅 Redis channel 转发
```

### 关键技术选型决策

**向量存储：pgvector 而非 ChromaDB / Milvus**

选择 PostgreSQL + pgvector 扩展，原因：
- 消除独立向量数据库中间件，所有持久化数据在同一个 PostgreSQL 实例，运维复杂度低
- pgvector 支持 IVFFLAT / HNSW 索引，百万级向量 p95 延迟 <10ms，满足本项目规模
- 检索可以混用 SQL 过滤（WHERE repository_id = ?）和向量相似度（ORDER BY embedding <=> :q），比独立向量库更灵活
- 面试时的回答：考虑过 Milvus（高并发写入场景更优），但 CodeSentinel 写入频率低、查询延迟要求中等，pgvector 够用且减少一个中间件依赖

**任务队列：ARQ 而非 Celery**

选择 ARQ 的理由：原生 async/await，与 FastAPI 同一个 asyncio 事件循环，无跨进程序列化开销；Celery 在纯异步栈里是额外复杂度。

---

### 架构约束（不可违反）

1. agents/ 节点函数**只改 ReviewState，不写 DB、不发网络请求**，副作用统一在 `review_task.py` 里处理
2. 所有 Git 平台操作**必须通过 GitPlatformAdapter 接口**，禁止在 task 里直接 import PyGithub
3. RAG 分块**必须用 AST 边界**，禁止固定字符数分块
4. LLM 调用**统一 streaming 模式**，每个 token publish 到 Redis，禁止等全部生成完再返回
5. 所有 DB 操作和 HTTP 调用**必须 async/await**，禁止在 async 上下文中阻塞调用

---

## 五、前端组件拆分

```
pages/          路由级页面，负责数据获取，组合子组件
  Dashboard.tsx      审查历史列表，调 GET /reviews，渲染 ReviewCard 列表
  ReviewDetail.tsx   单次审查详情，GET /reviews/{id} + WS 订阅，展示流式输出和问题列表
  Repositories.tsx   仓库注册/删除管理
  Metrics.tsx        统计图表（审查数趋势、问题类型分布饼图）

components/     纯展示组件，props-in，无直接 API 调用
  ReviewCard.tsx     列表项：状态徽章 + 仓库名 + PR 号 + 耗时 + 问题数
  IssueList.tsx      问题列表，按 critical/warning/suggestion 分组，可展开查看详情
  CodeViewer.tsx     Monaco Editor 封装，支持 diff 模式（原始代码 vs 修复建议）
  StreamOutput.tsx   流式文本追加展示，支持 Markdown 渲染
  StatusBadge.tsx    pending / running / done / failed 状态徽章

hooks/          数据与副作用逻辑，供 pages 调用
  useWebSocket.ts    WS 连接管理：连接、断线自动重连、消息解析（token/done/error）
  useReview.ts       GET/POST /reviews 封装，管理 loading/error 状态
  useRepositories.ts 仓库 CRUD API 封装

lib/
  api.ts    Axios 实例，统一 baseURL，错误拦截（401 跳登录、50x 显示 Toast）
  types.ts  TypeScript 接口：Review, Issue, Repository, MetricsSummary
  utils.ts  formatDuration（ms → "2.3s"）、formatDate、severityColor 等
```

### ReviewDetail 页面数据流

```
页面挂载
  ├─ GET /reviews/{id} 获取初始数据
  │     ├─ status = done    → 直接渲染 IssueList，不建 WS
  │     └─ status = pending/running → 建立 WS /ws/{id}
  │
WS 消息处理
  ├─ {type:"token"}  → 追加到 StreamOutput 文本
  ├─ {type:"done"}   → 重新 GET /reviews/{id}，刷新 IssueList，关闭 WS
  └─ {type:"error"}  → 显示错误提示，关闭 WS

用户交互
  └─ 点击「自动修复」→ POST /reviews/{id}/autofix
        └─ 沙箱验证通过后，CodeViewer 切换到 diff 模式展示 patch
```

---

## 六、Git 分支策略

采用 **GitHub Flow**（简化版，适合个人项目）。

### 分支规范

```
main                              始终保持可演示状态，每个里程碑合入后打 tag
  │
  ├── feat/mvp-backend-skeleton   后端骨架（FastAPI 启动 + ORM 建表）
  ├── feat/mvp-single-llm-review  单 LLM 调用审查接口
  ├── feat/mvp-streaming          Redis Pub/Sub + WebSocket 流式输出
  ├── feat/mvp-frontend           最简前端（粘贴代码 → 流式输出）
  │
  ├── feat/multi-agent-parallel   三路 Agent 并行（第 2 个月）
  ├── feat/rag-chunker            AST 分块实现
  ├── feat/rag-indexer            ChromaDB 索引 + 混合检索
  │
  ├── feat/github-webhook         GitHub Webhook 接入（第 3 个月）
  ├── feat/gitlab-webhook         GitLab 接入
  ├── feat/frontend-dashboard     完整前端 Dashboard
  │
  └── feat/eval-metrics           评测指标 + 测试覆盖（第 4 个月）
```

分支前缀：`feat/`（新功能）、`fix/`（Bug 修复）、`chore/`（配置/依赖更新）

### 版本标签

| Tag | 时间 | 内容 |
|-----|------|------|
| `v0.1.0` | 第 1 个月末 | MVP：单 LLM 审查 + 流式输出 + 最简前端 |
| `v0.2.0` | 第 2 个月末 | Multi-Agent 并行 + RAG 代码库理解 |
| `v0.3.0` | 第 3 个月末 | GitHub/GitLab 集成 + 完整前端 Dashboard |
| `v1.0.0` | 第 4 个月末 | 评测指标 + 测试 + 面试稳定版 |

### 为什么用分支

- `git log --oneline --graph` 展示完整开发历程，面试体现工程规范意识
- 每个 feat 分支对应一个完整可测试的功能单元，粒度合适
- `main` 始终是可演示状态，面试可直接 `git checkout v0.1.0` 演示 MVP
- GitHub PR 记录展示 Code Review 意识（哪怕是自己 Review 自己）
