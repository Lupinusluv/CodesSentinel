# CodeSentinel 项目规格文档

## 项目定位

**CodeSentinel** — AI 代码智能审查与自动修复平台

面向 AI 应用工程师秋招，展示 LLM + Multi-Agent + RAG 全栈工程能力。

---

## 核心功能

| 功能 | 描述 |
|------|------|
| 多平台接入 | 支持 GitHub / GitLab / Gitee，统一适配器接口 |
| 多 Agent 并行审查 | 安全漏洞、性能问题、代码规范三路并行，最终聚合 |
| RAG 代码库理解 | AST 级别分块，向量检索注入上下文 |
| 自动修复 | 生成 Patch → 沙箱执行验证 → 展示 diff |
| 实时流式输出 | WebSocket 推送审查进度，逐 token 显示 |
| Web Dashboard | 审查历史、统计指标、代码 diff 查看器 |
| 可量化指标 | 检测精确率、响应延迟、修复成功率 |

---

## 技术栈

### AI 层

| 组件 | 选型 |
|------|------|
| LLM | DeepSeek API（主）/ 兼容 OpenAI 格式 |
| Agent 框架 | LangGraph + LangChain |
| 代码解析 | Python `ast` + `tree-sitter`（多语言 AST 分块） |
| 向量数据库 | ChromaDB（本地开发）/ Qdrant（云部署可选） |
| 代码沙箱 | Docker exec / e2b 沙箱 API |

### 基础设施层

| 组件 | 选型 | 用途 |
|------|------|------|
| 关系数据库 | PostgreSQL + SQLAlchemy（async ORM） | 审查历史、仓库配置、统计指标 |
| 缓存 & 消息 | Redis | 任务队列 / WebSocket 广播 / LLM 缓存 / 限流 |
| 任务队列 | ARQ + Redis | 异步处理长时 AI 审查任务 |
| 后端 API | Python 3.11 + FastAPI + Uvicorn | 异步，与流式 LLM 天然匹配 |
| 监控（可选） | Prometheus + Grafana | 系统指标监控 |

### 平台集成层

| 组件 | 说明 |
|------|------|
| `GitPlatformAdapter`（抽象基类） | 统一操作接口：获取 PR diff、发布评论、设置 Status Check |
| `GitHubAdapter` | GitHub REST API + Webhook |
| `GitLabAdapter` | GitLab API v4 + Webhook，支持私有部署 |
| `GiteeAdapter` | Gitee API v5 + Webhook |

### 前端层

| 组件 | 选型 |
|------|------|
| 框架 | React + TypeScript + Tailwind CSS + shadcn/ui |
| 代码展示 | Monaco Editor（VSCode 同款，支持 diff 模式） |
| 实时通信 | WebSocket（审查进度流式推送） |

### 容器化

Docker Compose 编排全部服务：PostgreSQL + Redis + ChromaDB + Backend + Frontend

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
│   │   │   ├── reviews.py       # 审查 CRUD，触发审查
│   │   │   ├── repositories.py  # 仓库管理
│   │   │   ├── webhooks.py      # Git 平台 Webhook 接收
│   │   │   ├── metrics.py       # 统计指标查询
│   │   │   └── ws.py            # WebSocket 实时推送
│   │   ├── agents/
│   │   │   ├── graph.py         # LangGraph 图定义（主入口）
│   │   │   ├── state.py         # 图状态数据结构
│   │   │   ├── prompts.py       # 所有 Agent 的 System Prompt
│   │   │   ├── security_agent.py
│   │   │   ├── performance_agent.py
│   │   │   ├── style_agent.py
│   │   │   ├── synthesis_agent.py
│   │   │   └── autofix_agent.py
│   │   ├── rag/
│   │   │   ├── chunker.py       # AST 级别代码分块
│   │   │   ├── embeddings.py    # Embedding 封装
│   │   │   ├── indexer.py       # 仓库全量索引
│   │   │   └── retriever.py     # 混合检索（语义 + BM25）
│   │   ├── platform/
│   │   │   ├── base.py          # GitPlatformAdapter 抽象基类
│   │   │   └── adapters/
│   │   │       ├── github.py
│   │   │       ├── gitlab.py
│   │   │       └── gitee.py
│   │   ├── sandbox/
│   │   │   ├── executor.py      # 沙箱执行代码
│   │   │   └── validator.py     # 验证修复结果
│   │   ├── tasks/
│   │   │   ├── review_task.py   # 异步审查任务（ARQ Worker）
│   │   │   └── index_task.py    # 异步索引任务
│   │   ├── models/
│   │   │   ├── review.py        # Review 表
│   │   │   ├── repository.py    # Repository 表
│   │   │   └── issue.py         # Issue 表（审查发现的问题）
│   │   └── core/
│   │       ├── config.py        # 环境变量与全局配置
│   │       ├── dependencies.py  # FastAPI 依赖注入
│   │       └── logging.py       # 结构化日志
│   ├── tests/
│   │   ├── unit/
│   │   │   ├── test_agents.py
│   │   │   └── test_rag.py
│   │   └── integration/
│   │       └── test_review_flow.py
│   ├── main.py                  # FastAPI app 入口
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── Dashboard.tsx    # 审查历史总览
│       │   ├── ReviewDetail.tsx # 单次审查详情 + 实时流
│       │   ├── Repositories.tsx # 仓库管理
│       │   └── Metrics.tsx      # 统计指标面板
│       ├── components/
│       │   ├── ReviewCard.tsx   # 审查结果卡片
│       │   ├── CodeViewer.tsx   # Monaco Editor 封装（diff 模式）
│       │   ├── IssueList.tsx    # 问题列表（严重/警告/建议分级）
│       │   └── StreamOutput.tsx # 实时流式输出组件
│       ├── hooks/
│       │   ├── useWebSocket.ts  # WebSocket 连接管理
│       │   └── useReview.ts     # 审查相关 API 调用
│       └── lib/
│           ├── api.ts           # Axios/Fetch 封装
│           └── utils.ts         # 工具函数
├── scripts/
│   ├── init_db.py               # 初始化数据库表
│   └── seed_eval_set.py         # 生成评测集（含已知 Bug 样本）
├── docs/
│   ├── architecture.md          # 架构图（文字版）
│   └── api.md                   # API 接口文档
├── docker-compose.yml
├── .env.example
├── SPEC.md                      # 本文件
└── README.md
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
| repository_id | UUID | 外键 |
| pr_number | int | PR 编号 |
| status | enum | pending / running / done / failed |
| duration_ms | int | 审查耗时（毫秒） |
| total_issues | int | 发现问题总数 |
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

## 代码量目标

| 模块 | 目标行数 |
|------|---------|
| 后端（agents + rag + platform + api + models + tasks） | ~5,500 行 |
| 前端（pages + components + hooks + lib） | ~3,000 行 |
| 测试（unit + integration） | ~1,500 行 |
| **合计** | **~10,000 行** |

---

## 4 个月开发路线图

| 时间 | 里程碑 |
|------|--------|
| 第 1 个月 | 学习基础 + MVP（单 LLM 调用审查，流式输出，最简前端） |
| 第 2 个月 | Multi-Agent 系统 + RAG 代码库理解 |
| 第 3 个月 | Git 平台集成（Webhook + PR 评论）+ 完整前端 Dashboard |
| 第 4 个月 | 评测指标 + 测试 + 性能优化 + 面试材料准备 |

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
