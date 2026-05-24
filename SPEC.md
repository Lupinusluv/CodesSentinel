# CodeSentinel 项目规格文档

## 项目定位

**CodeSentinel** — AI 代码智能审查与自动修复平台

面向 AI 应用工程师秋招，展示 LLM + Multi-Agent + RAG 全栈工程能力。

---

## 当前实现进度（2026-05-24 更新）

### 实际进度 vs 计划

| 月份 | 计划内容 | 实际状态 |
|------|---------|---------|
| 第1个月（6月） | MVP + 流式输出 + 最简前端 | ✅ 已完成 |
| 第2个月（7月） | Multi-Agent 并行 + RAG 管道 | ✅ 已完成 |
| 第3个月（8月） | Git 平台集成 + 完整前端 Dashboard | ⚠️ 前端 100%，Git 集成 0% |
| 第4个月（9月） | 评测指标 + 测试 + 优化 + 面试准备 | ⏳ 未开始 |

> 现在是 5 月底，整体进度超前约 2 个月。

### 代码量现状

| 模块 | 当前行数 | 现实终点预估 |
|------|---------|------------|
| 后端 (app/) | 1,229 行 | ~2,800 行 |
| 前端 (src/) | 912 行 | ~1,400 行 |
| 测试 (tests/) | 242 行 | ~700 行 |
| **合计** | **2,383 行** | **~4,900 行** |

> 原规划 10,000 行不现实。4,900 行把所有功能做完比凑行数更有价值，面试考的是能讲清楚设计决策，不是数行数。

### 已完整实现的模块

**后端**
- `agents/`：graph.py、state.py、prompts.py、security/performance/style/synthesis_agent.py、llm.py、utils.py
- `rag/`：chunker.py（AST分块）、embeddings.py、indexer.py、retriever.py（混合检索）
- `api/v1/`：reviews.py（CRUD）、ws.py（WebSocket）、health.py
- `models/`：review.py、issue.py、repository.py、code_chunk.py
- `tasks/`：review_task.py（ARQ任务主逻辑）、worker.py
- `core/`：config.py、dependencies.py、logging.py

**前端（全部完成）**
- 5 个页面：NewReview、Dashboard、ReviewDetail、Repositories、Metrics
- 7 个组件：Layout、ReviewCard、CodeViewer（Monaco封装+diff模式）、IssueList、StatusBadge、StreamOutput、useReview hook
- React Router + NavLink 高亮路由

### 空文件 / 占位存根（待实现）

| 文件 | 状态 | 备注 |
|------|------|------|
| `platform/base.py` | 0 行 | GitPlatformAdapter 抽象基类 |
| `platform/adapters/github.py` | 0 行 | **最高优先级** |
| `platform/adapters/gitlab.py` | 0 行 | 结构同 GitHub，复制改造 |
| `platform/adapters/gitee.py` | 0 行 | 结构同 GitHub，复制改造 |
| `api/v1/webhooks.py` | 20 行 501 存根 | 需要真实签名验证+任务入队 |
| `api/v1/repositories.py` | 20 行 501 存根 | 需要真实 CRUD |
| `api/v1/metrics.py` | 14 行 501 存根 | 需要 SQL 统计查询 |
| `sandbox/executor.py` | 0 行 | Docker exec 沙箱 |
| `sandbox/validator.py` | 0 行 | 修复验证 |
| `agents/autofix_agent.py` | 0 行 | 自动修复 Agent |
| `tasks/index_task.py` | 0 行 | ARQ 仓库索引任务 |

### 下一步优先级

1. **GitHub Webhook 集成**（`platform/base.py` + `adapters/github.py` + `webhooks.py`）— 面试最高频追问点
2. **Repositories API 真实 CRUD**（`repositories.py`）— 前端 Repos 页解锁
3. **评测集**（`seed_eval_set.py` + 跑一次 P/R 数字）— **提前到 GitHub 集成完成后立刻做**，"精确率 82% vs baseline" 比任何功能描述都有杀伤力
4. **Metrics API 真实查询**（`metrics.py`）— 有了评测数据后顺手实现
5. **AutoFix**（AST 语法校验版，不做 Docker 沙箱）— 最后做，可作为加分项

---

## 核心功能

| 功能 | 描述 | 状态 |
|------|------|------|
| 多平台接入 | GitHub Webhook 完整实现；GitPlatformAdapter 接口支持多平台扩展 | ⏳ 适配器未实现 |
| 多 Agent 并行审查 | 安全/性能/规范三路并行，最终聚合 | ✅ 已完成 |
| RAG 代码库理解 | AST 分块 + pgvector 检索；Webhook 模式注入仓库上下文，paste 模式无 RAG | ✅ 管道已完成，Webhook 集成后生效 |
| 自动修复 | 生成 Patch → AST 语法校验 → 展示 diff（不做 Docker 沙箱执行） | ⏳ 未实现 |
| 实时流式输出 | WebSocket 推送审查进度，逐 token 显示 | ✅ 已完成 |
| Web Dashboard | 审查历史、统计指标、代码 diff 查看器 | ✅ 已完成 |
| 可量化指标 | 检测精确率、响应延迟、修复成功率 | ⏳ 未实现 |

---

## 技术栈

### AI 层

| 组件 | 选型 |
|------|------|
| LLM | DeepSeek API（主）/ 兼容 OpenAI 格式 |
| Agent 框架 | LangGraph + LangChain |
| 代码解析 | Python `ast` + `tree-sitter`（多语言 AST 分块） |
| 向量检索 | pgvector（集成在 PostgreSQL，余弦相似度）|
| 代码沙箱 | AST 语法校验（ast.parse / tsc --noEmit），不做 Docker exec |

### 基础设施层

| 组件 | 选型 | 用途 |
|------|------|------|
| 关系数据库 | PostgreSQL + SQLAlchemy（async ORM） | 审查历史、仓库配置、统计指标 |
| 缓存 & 消息 | Redis | 任务队列 / WebSocket 广播 / LLM 缓存 / 限流 |
| 任务队列 | ARQ + Redis | 异步处理长时 AI 审查任务 |
| 后端 API | Python 3.11 + FastAPI + Uvicorn | 异步，与流式 LLM 天然匹配 |

### 平台集成层

| 组件 | 说明 |
|------|------|
| `GitPlatformAdapter`（抽象基类） | 统一操作接口：获取 PR diff、发布评论、设置 Status Check |
| `GitHubAdapter` | GitHub REST API + Webhook，**完整实现** |
| GitLab / Gitee | 接口抽象支持扩展，按同一接口实现即可；面试展示平台无关的设计能力 |

### 前端层

| 组件 | 选型 |
|------|------|
| 框架 | React + TypeScript + Tailwind CSS + shadcn/ui |
| 代码展示 | Monaco Editor（VSCode 同款，支持 diff 模式） |
| 实时通信 | WebSocket（审查进度流式推送） |

### 容器化

Docker Compose 编排全部服务：PostgreSQL（含 pgvector 扩展）+ Redis + Backend + Frontend

---

## 系统架构（数据流）

```
Git 平台（GitHub/GitLab/Gitee）
        │  PR 事件 Webhook
        ▼
[webhooks.py] → 写入 ARQ 任务队列（Redis）
        │
        ▼
[review_task.py]（Worker 消费）
        ├─ 拉取 PR diff
        ├─ RAG 检索相关上下文（ChromaDB）
        │
        ▼
[LangGraph 审查图]
        ├─ SecurityAgent   ──┐
        ├─ PerfAgent       ──┼─ 并行执行
        ├─ StyleAgent      ──┘
        │
        ▼
[SynthesisAgent]  聚合结果 → 结构化报告（Pydantic）
        │
        ├─ 写入 PostgreSQL（持久化）
        ├─ 通过 Redis Pub/Sub → WebSocket → 前端实时展示
        └─ 调用 GitPlatformAdapter → 在 PR 页面发布评论

[AutoFixAgent]（可选触发）
        ├─ 生成 Patch
        ├─ Sandbox 执行验证
        └─ 返回验证后的 diff
```

---

## 目录结构

```
codessentinel/
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── reviews.py       ✅ 审查 CRUD，触发审查
│   │   │   ├── repositories.py  ⏳ 501 存根，待实现
│   │   │   ├── webhooks.py      ⏳ 501 存根，待实现
│   │   │   ├── metrics.py       ⏳ 501 存根，待实现
│   │   │   └── ws.py            ✅ WebSocket 实时推送
│   │   ├── agents/
│   │   │   ├── graph.py         ✅ LangGraph 图定义（主入口）
│   │   │   ├── state.py         ✅ 图状态数据结构
│   │   │   ├── prompts.py       ✅ 所有 Agent 的 System Prompt
│   │   │   ├── security_agent.py  ✅
│   │   │   ├── performance_agent.py ✅
│   │   │   ├── style_agent.py   ✅
│   │   │   ├── synthesis_agent.py ✅
│   │   │   └── autofix_agent.py ⏳ 0 行，待实现
│   │   ├── rag/
│   │   │   ├── chunker.py       ✅ AST 级别代码分块
│   │   │   ├── embeddings.py    ✅ Embedding 封装
│   │   │   ├── indexer.py       ✅ 仓库全量索引
│   │   │   └── retriever.py     ✅ 混合检索（语义 + BM25）
│   │   ├── platform/
│   │   │   ├── base.py          ⏳ 0 行，待实现
│   │   │   └── adapters/
│   │   │       ├── github.py    ⏳ 0 行，最高优先
│   │   │       ├── gitlab.py    ⏳ 0 行
│   │   │       └── gitee.py     ⏳ 0 行
│   │   ├── sandbox/
│   │   │   ├── executor.py      ⏳ 0 行，待实现
│   │   │   └── validator.py     ⏳ 0 行，待实现
│   │   ├── tasks/
│   │   │   ├── review_task.py   ✅ 异步审查任务（ARQ Worker）
│   │   │   └── index_task.py    ⏳ 0 行，待实现
│   │   ├── models/              ✅ 全部已实现
│   │   └── core/                ✅ 全部已实现
│   ├── tests/
│   │   ├── unit/                ⚠️ 骨架存在，覆盖率不足
│   │   └── integration/         ⚠️ 骨架存在，覆盖率不足
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/src/                ✅ 全部已实现
├── scripts/
│   ├── seed_eval_set.py         ⏳ 第4个月实现
│   └── dev-*.ps1                ✅ 开发启停脚本
├── docker-compose.yml
├── .env.example
└── SPEC.md
```

---

## 数据库表设计（概览）

### repositories
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| platform | enum | github / gitlab / gitee |
| url | str | 仓库地址 |
| webhook_secret | str | Webhook 验签密钥 |
| indexed_at | timestamp | 最近一次 RAG 索引时间 |

### reviews
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| repository_id | UUID | 外键（可为空，手动提交时） |
| pr_number | int | PR 编号（可为空，手动提交时） |
| status | enum | pending / running / done / failed |
| source_code | text | 手动提交时存储原始代码 |
| language | str | 代码语言 |
| duration_ms | int | 审查耗时（毫秒） |
| total_issues | int | 发现问题总数 |
| report_text | text | Synthesis Agent 生成的完整报告 |
| created_at | timestamp | |

### issues
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| review_id | UUID | 外键 |
| category | enum | security / performance / style |
| severity | enum | critical / warning / suggestion |
| file_path | str | 问题所在文件 |
| line_start | int | 起始行 |
| line_end | int | 结束行 |
| description | str | 问题描述 |
| suggestion | str | 修复建议 |
| fixed | bool | 是否已自动修复 |

---

## 面试核心设计决策（须能深度阐述）

1. **为什么用 LangGraph 而不是直接 LangChain？**
   → 支持有状态图、循环（修复后重新验证）、并行分支，比 Chain 更适合复杂 Agent 流程

2. **RAG 分块为什么用 AST 级别而不是固定字符数？**
   → 固定分块会截断函数体导致语义破碎；AST 按函数/类边界分块，检索精准度更高

3. **多 Agent 并行的挑战？**
   → 结果聚合时的冲突处理、Token 消耗控制、单 Agent 超时的降级策略

4. **如何量化项目效果？**
   → 构建含已知 Bug 的评测集，计算检测精确率（P）和召回率（R），对比 single-LLM baseline

5. **Webhook 安全如何保证？**
   → HMAC-SHA256 签名验证，密钥存 .env，每个仓库独立 secret

6. **流式输出的实现路径？**
   → LLM streaming → Redis Pub/Sub → WebSocket → 前端逐 token 追加，禁止等全部生成完再返回
