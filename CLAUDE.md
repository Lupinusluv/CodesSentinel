# CodeSentinel — CLAUDE.md


重要的条约：
- 选择 opus模型 + high思考 进行工作
- 每个对话开始工作前，向我询问你的职责，我会告诉你负责的是“编写代码”还是“架构和测试”
- git add commit 和 push 前，向我汇报并提醒我去找”架构和测试”会话先检测一遍，得到确认后再进行git提交
- 分支管理：”编写代码”只 push feature 分支；”架构和测试”负责 git merge --no-ff + tag + push main；合并到 main 只走 merge，禁止直接 push 或 squash push 到 main
- “架构和测试”对话，逻辑正确性由自动化保证；视觉/交互体验由人眼确认，避免过度耗时。此外，还需根据项目进度，每一阶段对”计划类”文档进行动态维护
- 上下文达到极限或你开始胡言乱语和力不从心的时候，主动提醒我去clear
- 拿到最新的架构/工作报告，先分析给出你的看法，不要急着直接改代码


## 项目概述

AI 代码智能审查与自动修复平台。接收 Git 平台（GitHub/GitLab/Gitee）的 PR Webhook，触发多 Agent 并行审查，将结果通过 WebSocket 实时推送到前端，并可在沙箱中自动验证修复 Patch。

详细规格（含实现进度和优先级）见 `SPEC.md`。

---

## 技术栈速查

- **后端**：Python 3.11 + FastAPI + SQLAlchemy（async）+ ARQ（任务队列）
- **AI**：LangGraph + LangChain + DeepSeek API（OpenAI 格式兼容）
- **存储**：PostgreSQL（主库）+ Redis（队列/缓存/Pub-Sub）+ ChromaDB（向量）
- **前端**：React + TypeScript + Tailwind CSS + shadcn/ui + Monaco Editor
- **容器**：Docker + Docker Compose

---

## 开发环境启动

```bash
# 启动全部基础服务（PostgreSQL + Redis + ChromaDB）
docker compose up -d postgres redis chromadb

# 后端
cd backend
pip install -r requirements.txt
alembic upgrade head               # 首次初始化 / 应用所有迁移
uvicorn main:app --reload --port 8000

# ARQ Worker（另开终端）
cd backend
arq app.tasks.worker.WorkerSettings

# 前端（另开终端）
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

> Webhook 本地开发需用 ngrok 暴露：`ngrok http 8000`

---

## 目录职责速查

```
backend/app/
├── agents/       LangGraph 图定义及各 Agent 实现
│   ├── graph.py          主图入口，定义节点和边
│   ├── state.py          ReviewState（图的共享状态，Pydantic）
│   ├── prompts.py        所有 Agent 的 System Prompt 常量
│   ├── security_agent.py
│   ├── performance_agent.py
│   ├── style_agent.py
│   ├── synthesis_agent.py
│   └── autofix_agent.py
├── rag/
│   ├── chunker.py        AST 级别代码分块（按函数/类边界）
│   ├── embeddings.py     Embedding 模型封装
│   ├── indexer.py        全量仓库索引到 ChromaDB
│   └── retriever.py      混合检索（语义 + BM25）
├── platform/
│   ├── base.py           GitPlatformAdapter 抽象基类
│   └── adapters/         github.py / gitlab.py / gitee.py
├── sandbox/
│   ├── executor.py       Docker exec 沙箱执行代码
│   └── validator.py      验证修复后测试是否通过
├── tasks/
│   ├── review_task.py    ARQ 审查任务（消费队列、驱动 LangGraph）
│   └── index_task.py     ARQ 索引任务
├── api/v1/
│   ├── reviews.py        GET/POST /reviews
│   ├── repositories.py   仓库注册与管理
│   ├── webhooks.py       接收 Git 平台 Webhook
│   ├── metrics.py        统计指标查询
│   └── ws.py             WebSocket /ws/{review_id}
├── models/               SQLAlchemy ORM 模型
└── core/
    ├── config.py         Settings（pydantic-settings，读 .env）
    ├── dependencies.py   FastAPI Depends 工厂函数
    └── logging.py        结构化日志（structlog）
```

---

## 架构约束（不要违反）

1. **平台无关**：所有与 Git 平台交互的代码必须通过 `GitPlatformAdapter` 接口，禁止在业务逻辑里直接调用 GitHub/GitLab/Gitee SDK。

2. **Agent 无副作用**：LangGraph 节点函数只修改 `ReviewState`，不直接写数据库或发网络请求；副作用由 `review_task.py` 在图执行完后统一处理。

3. **RAG 分块粒度**：`chunker.py` 必须使用 AST 边界（函数/类级别）分块，禁止使用固定字符数分块。

4. **流式输出**：LLM 调用统一使用 streaming 模式，通过 Redis Pub/Sub 推送到 WebSocket，禁止等全部生成完再一次性返回。

5. **异步优先**：所有数据库操作、HTTP 调用使用 `async/await`，禁止在 async 上下文中使用同步阻塞调用。

6. **结构化输出**：各 Agent 的输出必须定义 Pydantic 模型（放在 `state.py`），禁止直接解析 LLM 返回的纯文本字符串。

---

## 环境变量（`.env.example` 为准）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（主 LLM） |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com/v1` |
| `DATABASE_URL` | PostgreSQL 连接串 |
| `REDIS_URL` | Redis 连接串 |
| `CHROMA_HOST` / `CHROMA_PORT` | ChromaDB 地址 |
| `GITHUB_WEBHOOK_SECRET` | GitHub Webhook 验签密钥 |
| `GITLAB_WEBHOOK_SECRET` | GitLab Webhook 验签密钥 |
| `GITEE_WEBHOOK_SECRET` | Gitee Webhook 验签密钥 |

---

## 常用命令

```bash
# 运行测试
cd backend && pytest tests/ -v

# 只跑单元测试
pytest tests/unit/ -v

# 数据库迁移（在 backend/ 目录下运行）
cd backend
alembic upgrade head              # 应用所有迁移（首次初始化也用这个）
alembic revision --autogenerate -m "描述"   # 新增字段后自动生成迁移文件
alembic downgrade -1              # 回滚最近一次迁移

# 生成评测集
python scripts/seed_eval_set.py

# 前端类型检查
cd frontend && npx tsc --noEmit

# 构建生产镜像
docker compose build
```

---

## 代码规范

- Python：Black 格式化，行宽 100；类型注解覆盖所有函数签名
- TypeScript：ESLint + Prettier；禁止 `any`
- 提交信息：`feat:` / `fix:` / `refactor:` / `test:` 前缀
- 不写解释"做了什么"的注释，只写解释"为什么"的注释
