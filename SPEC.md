# CodeSentinel 项目规格文档

## 项目定位

**CodeSentinel** — AI 代码智能审查与自动修复平台

面向 AI 应用工程师秋招，展示 LLM + Multi-Agent + RAG 全栈工程能力。

---

## 当前实现进度（2026-05-29 更新，v0.4.5 已 tag）

### 实际进度 vs 计划

| 月份 | 计划内容 | 实际状态 |
|------|---------|---------|
| 第1个月（6月） | MVP + 流式输出 + 最简前端 | ✅ 已完成 |
| 第2个月（7月） | Multi-Agent 并行 + RAG 管道 | ✅ 已完成 |
| 第3个月（8月） | Git 平台集成 + 完整前端 Dashboard | ✅ GitHub Webhook + 前端全部完成；GitLab/Gitee 适配器仍为空（可选补充） |
| 第4个月（9月） | 评测指标 + AutoFix + 优化 + 面试准备 | ✅ 评测集完成；AutoFix MVP 完成（v0.4.0） |

> 现在是 5 月底，整体进度超前约 3 个月，全部核心功能已实现。

### Patch 版本历史

| 版本 | 主要改动 |
|------|---------|
| v0.4.0 | AutoFix MVP（agent + sandbox + patches 表 + PatchPanel UI + 41 tests） |
| v0.4.1 | LLM 入参从行级片段改为整文件，patch 成功率 20% → 100% |
| v0.4.2 | rerun 安全（清旧 + 不累加 + race fix）+ 同行 issue 聚合（pick 最高 severity）+ per-patch 复制/下载 + FinalPatchCard（额外 LLM 调用产出综合修复版）+ 下载文件名 setTimeout 修复 |
| v0.4.3 | 下载自选目录（File System Access API + 降级 a.click）+ conftest user 拼写修正 + Monaco DiffEditor unmount race 修复（onMount cleanup） |
| v0.4.5 | webhook/回写路径测试硬化（+13 集成测试，覆盖验签/事件过滤/入队/status 状态逻辑/PR 评论）+ webhook 路由改 ArqPoolDep 注入（可测性）+ 修 happy-path 响应类型 bug（int pr 撞 dict[str,str] 校验导致 500→已放行 int），为 v0.5.0 上线前置 |

### 代码量现状

| 模块 | 当前行数 | 现实终点预估 |
|------|---------|------------|
| 后端 (app/) | ~2,700 行 | ~2,800 行 |
| 前端 (src/) | ~1,290 行 | ~1,400 行 |
| 测试 (tests/) | ~420 行 | ~500 行 |
| 评测脚本 (scripts/) | 357 行 | ~400 行 |
| **合计** | **~4,767 行** | **~5,100 行** |

> 原规划 10,000 行不现实。5,100 行把所有功能做完比凑行数更有价值，面试考的是能讲清楚设计决策，不是数行数。

### 已完整实现的模块

**后端**
- `agents/`：graph.py、state.py、prompts.py、security/performance/style/synthesis_agent.py、utils.py（lane 隔离 + 置信度约束已调优）
- `rag/`：chunker.py（AST分块）、embeddings.py、indexer.py、retriever.py（混合检索）
- `api/v1/`：reviews.py（CRUD + severity 排序）、repositories.py（完整 CRUD）、webhooks.py（GitHub 完整验签 + 入队）、metrics.py（SQL 聚合）、ws.py（WebSocket）、health.py
- `models/`：review.py、issue.py、repository.py、code_chunk.py
- `tasks/`：review_task.py（ARQ 审查主逻辑）、index_task.py（仓库 RAG 索引）、worker.py
- `core/`：config.py、dependencies.py、logging.py
- `platform/`：base.py（GitPlatformAdapter 抽象基类）、adapters/github.py（完整实现）
- `scripts/run_eval.py`：eval harness（n=40 样本，greedy bipartite P/R/F1 matching）
- `scripts/eval_data/`：security / performance / style 三类各 10 个带标注样本

**前端（全部完成）**
- 5 个页面：NewReview、Dashboard（History）、ReviewDetail、Repositories、Metrics
- 组件：Layout、ReviewCard、IssueList、StatusBadge、StreamOutput、useReview hook
- React Router + NavLink 高亮路由；Monaco Editor 代码编辑器

**基础设施**
- Docker Compose：postgres（pgvector）+ redis + backend + worker + frontend 五服务健康检查链
- Alembic 迁移：0001_initial_schema（4 enums + 5 tables）；0002_add_patches_table（patch_status_enum + patches 表）

### 空文件 / 占位存根

| 文件 | 状态 | 备注 |
|------|------|------|
| `platform/adapters/gitlab.py` | 0 行 | 结构同 GitHub，按需补充（可选） |
| `platform/adapters/gitee.py` | 0 行 | 结构同 GitHub，按需补充（可选） |
| `sandbox/executor.py` | ✅ 已实现 | Python ast.parse + node --check |
| `sandbox/validator.py` | ✅ 已实现 | validate_patch + make_unified_diff |
| `agents/autofix_agent.py` | ✅ 已实现 | generate→validate 两节点 LangGraph 图 |

### 下一步优先级（v0.5.0 方向，可选）

1. **GitLab 适配器** — 体现平台无关设计能力，可选补充
2. **AutoFix 片段上下文重建** — 当前 AST 校验对行级片段成功率低（已知局限），可扩展为全函数上下文替换
3. **面试准备** — 梳理设计决策文档、准备 demo 剧本

### 已知问题（v0.5.0 实战暴露）

- **RAG embedding 端点错配 —— 生产 RAG 从未真正工作**：`rag/embeddings.py` 用模型名 `text-embedding-v3` 打 DeepSeek `/embeddings`，但该模型名属阿里通义（DashScope），DeepSeek 并无 embeddings 端点，调用必返回 404。单测 mock 了 embedding、paste 模式不调用，故一直未暴露；v0.5.0 webhook 实战首次走真实已注册仓库路径时触发，worker 日志原文：

  ```
  response = await client.embeddings.create(
  openai.NotFoundError: Error code: 404
  ```

  **v0.5.0 已止血**：`retrieve_context` 在 embedding 失败时优雅降级返回 `""`，审查照常进行（仅缺 RAG 上下文），不再让整个 review 崩溃。
  **v0.5.1 候选决策（待架构定）**：换用支持 embedding 的 provider（OpenAI / Voyage / Jina / 阿里 DashScope / 本地模型），或彻底关闭 RAG 管道。

---

## 核心功能

| 功能 | 描述 | 状态 |
|------|------|------|
| 多平台接入 | GitHub Webhook 完整实现；GitPlatformAdapter 接口支持多平台扩展 | ⏳ 适配器未实现 |
| 多 Agent 并行审查 | 安全/性能/规范三路并行，最终聚合 | ✅ 已完成 |
| RAG 代码库理解 | AST 分块 + pgvector 检索；Webhook 模式注入仓库上下文，paste 模式无 RAG | ⚠️ 管道完成，但 embedding 端点错配致生产从未生效（见「已知问题」）；失败已优雅降级，不阻塞审查 |
| 自动修复 | 生成 Patch → AST 语法校验 → Monaco DiffEditor 展示（不做 Docker 沙箱执行） | ✅ MVP 完成（v0.4.0） |
| 实时流式输出 | WebSocket 推送审查进度，逐 token 显示 | ✅ 已完成 |
| Web Dashboard | 审查历史、统计指标、代码 diff 查看器 | ✅ 已完成 |
| 可量化指标 | 检测精确率、响应延迟、修复成功率 | ✅ eval harness 完成（n=40，P/R/F1）；修复成功率可从 patches 表 syntax_valid 字段统计 |

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
│   │   │   ├── reviews.py       ✅ 审查 CRUD，severity 排序
│   │   │   ├── repositories.py  ✅ 完整 CRUD
│   │   │   ├── webhooks.py      ✅ GitHub 验签 + 入队；GitLab/Gitee 存根
│   │   │   ├── metrics.py       ✅ SQL 聚合（总数/耗时/分布）
│   │   │   ├── health.py        ✅ /api/v1/health
│   │   │   └── ws.py            ✅ WebSocket 实时推送
│   │   ├── agents/
│   │   │   ├── graph.py         ✅ LangGraph 图定义（主入口）
│   │   │   ├── state.py         ✅ 图状态数据结构
│   │   │   ├── prompts.py       ✅ 所有 Agent 的 System Prompt（lane 隔离已调优）
│   │   │   ├── security_agent.py  ✅
│   │   │   ├── performance_agent.py ✅
│   │   │   ├── style_agent.py   ✅
│   │   │   ├── synthesis_agent.py ✅
│   │   │   └── autofix_agent.py ⏳ 0 行，v0.4.0 实现
│   │   ├── rag/
│   │   │   ├── chunker.py       ✅ AST 级别代码分块
│   │   │   ├── embeddings.py    ✅ Embedding 封装
│   │   │   ├── indexer.py       ✅ 仓库全量索引
│   │   │   └── retriever.py     ✅ 混合检索（语义 + BM25）
│   │   ├── platform/
│   │   │   ├── base.py          ✅ GitPlatformAdapter 抽象基类
│   │   │   └── adapters/
│   │   │       ├── github.py    ✅ 完整实现
│   │   │       ├── gitlab.py    ⏳ 0 行，按需补充
│   │   │       └── gitee.py     ⏳ 0 行，按需补充
│   │   ├── sandbox/
│   │   │   ├── executor.py      ⏳ 0 行，v0.4.0 实现
│   │   │   └── validator.py     ⏳ 0 行，v0.4.0 实现
│   │   ├── tasks/
│   │   │   ├── review_task.py   ✅ 异步审查任务（ARQ Worker）
│   │   │   └── index_task.py    ✅ ARQ 仓库 RAG 索引任务
│   │   ├── models/              ✅ 全部已实现
│   │   └── core/                ✅ 全部已实现
│   ├── alembic/versions/        ✅ 0001_initial_schema（4 enums + 5 tables）
│   ├── tests/
│   │   ├── unit/                ⚠️ 197 行，覆盖率不足，v0.4.0 补充
│   │   └── integration/         ⚠️ 骨架存在，待补充
│   ├── scripts/
│   │   ├── run_eval.py          ✅ eval harness（n=40，P/R/F1）
│   │   └── eval_data/           ✅ security / performance / style 各 10 样本
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/src/                ✅ 全部已实现（5 页面 + 组件 + hooks）
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
