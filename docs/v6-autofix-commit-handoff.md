# V6 交接文档 — AutoFix「一键修复并提交分支 / 开 PR」

> 写给下一个会话（很可能是 clear 后的新上下文）。读完这份 + `SPEC.md` + 本目录
> `audit-2026-06-03-full-codebase.md` 就能冷启动接上 V6，不需要回溯历史对话。
> 本文档由「架构和测试」会话在 V5 收尾（v0.5.4，CI 绿）后写就。

---

## 0. 当前基线（开工前必须知道）

- **分支/版本**：`main` 干净，最新 tag `v0.5.3 → v0.5.4`，CI 全绿（ruff → black → alembic → pytest）。
- **③ 全仓审计线已清零**，实质分 ~88。P1/P2 落地记录见 `audit-2026-06-03-full-codebase.md` §5。
- **AutoFix 现状**：已能「生成补丁 → 语法校验 → 前端下载/复制」，**但只到 patch，不落地到仓库**。
  V6 就是把最后一跳补上：把校验通过的补丁**提交到一个新分支并开 PR（不自动 merge）**。

---

## 1. V6 目标（一句话）

审查完 → 一键 AutoFix → 校验通过的补丁**写回仓库的新分支并开 PR**，人来 review & merge。
**红线：永不自动 merge、永不直接 push 到用户的默认分支。**只开 PR，决定权留给人。

---

## 2. 为什么不是「小扩展」——四个前置硬骨头

按依赖顺序排列，**每一个都得在写「提交」逻辑前解决**：

### 骨头 ① webhook 模式存的是 diff，不是整文件 ★最硬
- `review_task.py::_fetch_pr_diff`（L176-194）把 **PR diff** 整个塞进 `review.source_code`。
- autofix 拿 `review.source_code` 当「原始代码」去生成补丁——**diff 不是可提交的文件内容**。
- 要提交回仓库，必须能拿到**受影响文件的完整内容**（按 file_path 逐个拉 blob），在其上打补丁，
  得到新文件全文，再 commit。
- **决策点**：是改 `_fetch_pr_diff` 额外拉全文件（按 PR changed files 列表逐个 `GET contents`），
  还是 AutoFix 时按需懒加载？倾向后者（审查阶段不需要全文，只 autofix 才需要）。

### 骨头 ② file_path 没有端到端打通 ★次硬
- `Issue` 模型**有** `file_path` 字段，但：
  - `autofix_task.py::_group_issues_by_range`（L39）只按 `(line_start, line_end)` 聚合，**丢掉了 file_path**。
  - `IssueRef` / `PatchOutput`（`autofix_agent.py`）**都不带 file_path**。
  - 整条 autofix 管线是**「单文件隐式」**：source_code 一整块字符串，补丁对整块做替换。
- 多文件 PR 要提交，必须让 file_path 贯穿 group → IssueRef → PatchOutput → commit。
  这是 V6 改动量最大的一块（涉及 state schema + 聚合逻辑 + 可能的 DB 迁移）。
- **聚合 key 要从 `(line_start, line_end)` 升级成 `(file_path, line_start, line_end)`。**

### 骨头 ③ 适配器没有「写」能力
- `GitPlatformAdapter`（`platform/base.py`）现有方法：`get_pr_diff` / `post_review_comment` /
  `set_commit_status`——**全是读 + 评论，没有写仓库**。
- V6 要给 `GitHubAdapter` 新增（并在 base 抽象里声明）：
  - `get_file_content(owner, repo, path, ref) -> str`（骨头①需要）
  - `create_branch(owner, repo, new_branch, base_sha)` 
  - `commit_files(owner, repo, branch, files: dict[path, content], message)`（或逐文件 PUT contents）
  - `create_pull_request(owner, repo, head, base, title, body) -> pr_url`
- gitlab/gitee 仍只是 roadmap 骨架（抛 NotImplementedError），**V6 只做 GitHub**。

### 骨头 ④ 写权限 + 安全
- 现在 GitHub 调用用的 token 来源/scope 要确认能 `contents:write` + `pull_requests:write`
  （只读 PAT 不够）。这是 GitHub App / PAT 的 scope 问题，要在 spec 阶段定清楚。
- paste 模式（`repository_id=None`）**没有仓库可提交**，V6 功能对 paste 模式必须优雅禁用
  （前端按钮置灰 + 后端 422）。

---

## 3. 关键代码地图（V6 会动到的文件）

| 文件 | 现状 | V6 要做什么 |
|------|------|------------|
| `backend/app/platform/base.py` | 3 个只读方法 | 加写方法抽象声明 |
| `backend/app/platform/adapters/github.py` | 只读 + 评论 | 实现 get_file_content / create_branch / commit / create_pr |
| `backend/app/agents/autofix_agent.py` | IssueRef/PatchOutput 无 file_path | state schema 加 file_path |
| `backend/app/tasks/autofix_task.py` | 按行号聚合、单文件隐式 | 聚合 key 加 file_path；新增「提交」步骤或拆独立 task |
| `backend/app/tasks/review_task.py` | `_fetch_pr_diff` 存 diff | 看决策①：是否补「拉全文件」能力 |
| `backend/app/api/v1/reviews.py` | 有 `/autofix` 入队端点 | 加 `/autofix/commit`（或参数）触发提交+开 PR |
| `backend/app/models/patch.py` | 有 review_id/issue_id/diff 等 | 可能加 file_path（若决定持久化） |
| `frontend/.../PatchPanel.tsx` | 下载/复制 | 加「提交到分支并开 PR」按钮 + PR 链接展示 + paste 模式置灰 |

> 注：`autofix_task.py` 已和 `review_task.py` **严格对称**（task 管所有 DB IO，图节点无副作用）——
> V6 新逻辑必须延续这个边界，提交/开 PR 的网络副作用放 task 层，不进图节点。

---

## 4. 推荐的开工路径

**先 brainstorm，别急着写代码**（CLAUDE.md 红线 + superpowers brainstorming skill）。

### 4.1 已敲定的设计决策（V5 收尾会话与用户当面确认，作为 V6 既定起点）

- **【已定】提交模型 = A「修在 PR 之上」**：从原 PR 的 head SHA 切新分支 → 提交修复 →
  开 PR：`autofix 分支 → 原 PR 的 head 分支`。作者把修复 merge 回**自己的 PR**。
  **由此「永不碰用户默认分支」天然成立**——修复 PR 只挂在原 PR 旁边，决定权留给人。
  （否决了模型 B「直接开 PR 进 main」：绕过原 PR、语义混乱、易与原 PR 冲突。）
- **【已定】交互 = 弹窗确认，绝不静默自动开 PR**。MVP 弹窗尽量预填、少让用户填：
  - 分支名：预填默认值、可编辑
  - 提交到（base）：只读，自动推断为原 PR 的 head 分支
  - 包含补丁：默认只提交 syntax_valid 的
  - PR 标题/正文：预填可编辑
  - 按钮：[取消] / [创建分支并开 PR]
- **【已定】默认分支名按模式区分**：
  - Webhook/PR 模式：基于原 PR head 分支名，如 `feat/login` → `feat/login-autofixed`（连字符）。
  - Paste 模式（`repository_id=None`）：**整个功能禁用**，按钮置灰、弹窗不出现、后端 422。
    粘贴代码没有仓库/分支可提交，这是硬约束不是选项。
- **【暂定，可在 brainstorm 再议】碰撞策略**：默认名已存在时**加短时间戳后缀**
  （如 `feat/login-autofixed-0603`），**不 force-push**（强推覆盖太危险）。

### 4.2 仍需 brainstorm 敲定的决策

1. **提交粒度**：一个 PR 含所有修复，还是按文件拆多个 PR？（倾向：一个 PR 全量）
2. **触发方式**：复用现有 `/autofix` 加 `commit=true` 参数，还是独立端点 `/autofix/commit`？
3. **token/权限**：用哪种凭证拿写权限（GitHub App 安装 token vs PAT，需 `contents:write` +
   `pull_requests:write`）。
4. **骨头①的取法**：审查时顺手拉全文件，还是 autofix 时懒加载。（倾向：懒加载）
5. **碰撞策略最终拍板**（见 4.1 暂定项）。

定完 → `superpowers:writing-plans` 出 spec → 实现 → 「架构和测试」会话验收 git。

---

## 5. 工作纪律（CLAUDE.md，新会话必读）

- 开工先问职责：你是「编写代码」还是「架构和测试」。本文档作者是后者。
- **git 红线**：commit/push 前先汇报、等用户确认；「编写代码」只 push feature 分支；
  「架构和测试」负责 `merge --no-ff` + tag + push main；**禁止直接 push / squash push 到 main**。
- 模型用 **opus + high 思考**。
- Python Black 行宽 100、全类型注解；TS 禁 `any`；注释只写「为什么」。
- 提交多行中文用消息文件 `git commit -F`（PowerShell here-string 会乱码）。
- CI 为准：本地 `.env` 会掩盖缺环境变量类回归。`GITHUB_TOKEN` 从 repo 根 `.env` 读、不打印，
  用来轮询 Actions（`grep -E '^GITHUB_TOKEN=' .env | cut -d= -f2-`）。

---

## 6. 不在 V6 范围（避免 scope 蔓延）

- gitlab/gitee 的写实现（仍是 roadmap 骨架）。
- L6 串行 embedding 并发化、L7 检索粒度（MVP 局限，已决策不改）。
- ④/⑤ tantai.xyz 线上验证、架构图 + 10s GIF、B6 i18n（属「冲星」收尾线，与 V6 并行的另一条线）。
- `frontend/README.md`（Vite 脚手架样板残留，无害，未纳管，要清可顺手删）。
