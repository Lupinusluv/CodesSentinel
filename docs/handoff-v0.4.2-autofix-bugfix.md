# v0.4.2 工作交接 v2（覆盖原版）

**来源**：架构和测试会话于 2026-05-27 完成 v0.4.2 第一轮验收后发现 3 个新问题，与原 3 个修复合并。
**给谁**：编写代码会话。
**分支**：继续在 `fix/autofix-ux-v0.4.2` 上叠加 commit（已有 #2/#3/#4/#5/#6/#7 改动未 commit），完成后**整体一次性 commit + push**。

---

## 修复清单（共 7 项，按依赖顺序）

| # | 修复项 | 状态 |
|---|---|---|
| #2 | 重跑 AutoFix 清旧 patches | ✅ 上一轮已完成（保留） |
| #3 | 同行 issue 聚合 | ✅ 上一轮已完成（保留） |
| #4 | 复制 / 下载按钮 | ✅ 上一轮已完成（保留） |
| #5 | 轮询停止条件 + setPatches([]) + 空态文案 | ✅ 上一轮已完成（保留） |
| **#6** | **polling race fix：trigger 接口同步清旧 patches** | 🆕 本轮 |
| **#7** | **下载文件名丢失：revokeObjectURL 延后** | 🆕 本轮 |
| **#8** | **综合修复版 FinalPatch（方案 A）** | 🆕 本轮，工作量最大 |

---

## #6 polling race fix

### 根因

`run_autofix_task` 把 `DELETE 旧 patches → INSERT 新 patches` 放在**同一事务**。
事务 COMMIT 前其他 session 看到旧 14 patches（全 done）。
前端在 trigger 后 2 秒第一次 polling 拉到这批旧数据 → 满足 `length>0 && every(non-pending)` 立刻 stopPolling → 永不更新到新的 5 patches。

→ 用户演示时**重跑一定会看到旧数据残留**，比原 bug 更糟。

### 修复

在 `backend/app/api/v1/patches.py:trigger_autofix` 入队 ARQ job **之前**同步 DELETE + COMMIT 旧 patches：

```python
from sqlalchemy import delete
from app.models.patch import Patch

@router.post("/{review_id}/autofix", ...)
async def trigger_autofix(review_id: str, db: DBSessionDep, arq: ArqPoolDep) -> AutoFixTriggerResponse:
    # ...existing validation...

    # race fix：让 polling 永远拉不到上一轮残留
    await db.execute(delete(Patch).where(Patch.review_id == uid))
    await db.commit()

    await arq.enqueue_job("run_autofix_task", review_id)
    return AutoFixTriggerResponse(review_id=review_id, status="queued")
```

`run_autofix_task` 里的 DELETE 保留作幂等保护，不重复写。

### 验收

新增集成测试 `tests/integration/test_autofix_trigger_clears.py`：

```python
async def test_trigger_immediately_clears_old_patches(http_client, db_session, patched_arq):
    """POST /autofix 接口返回后立即 GET /patches 应当返回 0 条。"""
    # seed review + 旧 patches
    # POST /autofix
    # GET /patches → assert total == 0
```

注意：用 `http_client` 而不是 `patched_task`，因为这是 API 层行为，不是 task 层。

---

## #7 下载文件名丢失

### 根因

`frontend/src/components/PatchPanel.tsx:handleDownload` 在 `a.click()` 之后**立刻** `URL.revokeObjectURL(url)`。
浏览器对 blob 下载的实际处理是**异步**的——click 同步触发后，浏览器后台再读 blob 时已经被 revoke，
fallback 用 blob URL 末尾的 UUID 当文件名（无扩展名），且**忽略 `a.download` 属性**。

用户截图证据：下载历史显示 `c069a0ed-2b3c-49ec-...` 这种 UUID 而不是 `fixed-484e39bd.py`。

### 修复

`PatchPanel.tsx:handleDownload` 把 revoke 延后到下一个事件循环（足够让浏览器异步流程取完属性）：

```ts
const handleDownload = () => {
  const ext = LANG_EXT[language.toLowerCase()] ?? 'txt'
  const blob = new Blob([patch.fixed_code], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `fixed-${patch.issue_id.slice(0, 8)}.${ext}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // 关键：延后 revoke，否则 Chromium 异步下载流程拿不到 download 属性，
  // 文件名会 fallback 到 blob URL 末尾的 UUID
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
```

同一修复同样应用到 **#8 FinalPatchCard 的下载按钮**（见下）。

### 验收

人眼：真实浏览器点 ⬇ 下载 → 浏览器下载历史里显示 `fixed-XXXXXXXX.py`，不是 UUID。

---

## #8 综合修复版 FinalPatch（方案 A）⭐

### 动机

现有 5 个 patch 每个**只修了一个 issue group**。用户复制任何一个都不是真正可用的"最终代码"——因为其他 issue 还在。
我们需要在 N 个独立 patch 之外**额外**产出一份"修复了所有 issue 的综合版"，**突出展示在 UI 顶部**带大复制/下载按钮。

### 设计取舍

不选"只跑 1 次 LLM 一次性修全部"——会失去 per-issue 演示叙事。
不选"前端 patch diff 合并"——3-way merge 冲突难处理。
**选**：保留 N 个独立 patch，**额外**跑 1 次综合 LLM 调用产出 final patch。

---

### 8.1 数据模型变更

在 `backend/app/models/patch.py:Patch` 加字段：

```python
is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
```

**Alembic 迁移**：`backend/alembic/versions/0003_add_patch_is_final.py`

```python
"""add patches.is_final

Revision ID: 0003_add_patch_is_final
Revises: 0002_add_patches_table
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_add_patch_is_final"
down_revision = "0002_add_patches_table"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column(
        "patches",
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

def downgrade():
    op.drop_column("patches", "is_final")
```

**注意**：因为 `is_final=True` 的 patch 也指向某个 issue（取所有 issue 中 severity 最高那条作为 representative），`issue_id NOT NULL` 约束保留不变。

---

### 8.2 后端图节点

`backend/app/agents/autofix_agent.py` 增加 `merge_all_node`：

```python
async def merge_all_node(state: AutoFixState) -> dict:
    """跑完 generate + validate 之后，再让 LLM 综合所有 issue 一次性修复。
    
    返回的 patch 标 is_final=True；issue_id 是所有 issue 中 severity 最高那个的 id。
    """
    patches = state.get("patches", [])
    issues = state["issues"]
    if not issues:
        return {}  # 不改 patches
    
    # 找 severity 最高的 issue 作为 final patch 的 representative
    # （注意 issues 是 IssueRef，不带 severity，需要换一种方式）
    # → 推荐：task 层在 group 时记录 critical_rep_id，传进 state
    
    # 综合 prompt
    desc_block = "\n".join(f"- {i.description}" for i in issues)
    sug_block = "\n".join(f"- {i.suggestion}" for i in issues if i.suggestion)
    
    messages = [
        SystemMessage(content=AUTOFIX_FINAL_SYSTEM_PROMPT),
        HumanMessage(content=build_autofix_final_prompt(
            language=state["language"],
            source_code=state["source_code"],
            all_issues_desc=desc_block,
            all_issues_suggestions=sug_block or "(no specific suggestions)",
        )),
    ]
    
    llm = get_llm(temperature=0.0, tags=["autofix-final"])
    try:
        response = await llm.ainvoke(messages)
        fixed = _extract_code(response.content or "")
        if not fixed:
            return {}
    except Exception as exc:
        log.warning("autofix_final_llm_error", error=str(exc))
        return {}
    
    # 同 generate 流程：跑 syntax 校验
    valid, err = await check_syntax(fixed, state["language"])
    diff = make_unified_diff(state["source_code"], fixed)
    
    final_patch = PatchOutput(
        issue_id=state["final_rep_id"],   # ← 由 task 层注入
        original_code=state["source_code"],
        fixed_code=fixed,
        diff=diff,
        syntax_valid=valid,
        error_msg=err,
        status=PatchStatus.done if valid else PatchStatus.failed,
    )
    # 把 final_patch 拼到现有 patches 列表的开头
    return {"patches": [final_patch, *patches]}
```

**注意**：`PatchOutput` 上 `is_final` 没字段，task 层根据"列表第一条且 is_final=True 标记"约定写入。或者**更干净**：给 `PatchOutput` 加 `is_final: bool = False` 字段。**推荐加字段**。

#### AUTOFIX_FINAL_SYSTEM_PROMPT 和 build_autofix_final_prompt

放在 `backend/app/agents/prompts.py`：

```python
AUTOFIX_FINAL_SYSTEM_PROMPT = (
    "You are a senior software engineer producing a final consolidated fix for all\n"
    "known issues in a source file.\n"
    "\n"
    "You will receive:\n"
    "- A complete source file\n"
    "- A list of ALL issues found in this file (with line ranges and descriptions)\n"
    "- Optional suggestions for each issue\n"
    "\n"
    "Your task: fix EVERY issue listed, in a single coherent revision of the file.\n"
    "Preserve all unrelated code. Do not rename variables or refactor anything unrelated.\n"
    "\n"
    "# Output format\n"
    "Output ONLY the complete fixed source file, enclosed in a single fenced code block\n"
    "using triple backticks. Include ALL lines. No prose before or after the block.\n"
)


def build_autofix_final_prompt(
    *,
    language: str,
    source_code: str,
    all_issues_desc: str,
    all_issues_suggestions: str,
) -> str:
    return (
        f"## Language\n{language}\n\n"
        f"## All issues to fix\n{all_issues_desc}\n\n"
        f"## Suggestions\n{all_issues_suggestions}\n\n"
        f"## Full source code\n"
        f"```{language}\n{source_code}\n```\n\n"
        "Fix ALL of the above issues in a single consolidated revision. "
        "Return the ENTIRE fixed source file in a fenced code block."
    )
```

#### 图编译

`build_autofix_graph` 加节点和边：

```python
def build_autofix_graph() -> StateGraph:
    graph = StateGraph(AutoFixState)
    graph.add_node("generate", generate_patches_node)
    graph.add_node("validate", validate_patches_node)
    graph.add_node("merge_all", merge_all_node)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", "merge_all")
    graph.add_edge("merge_all", END)
    return graph
```

---

### 8.3 AutoFixState 增加字段

```python
class AutoFixState(TypedDict):
    review_id: str
    source_code: str
    language: str
    issues: list[IssueRef]
    patches: list[PatchOutput]
    error: str | None
    final_rep_id: str    # ← 新增：所有 issue 里 severity 最高那条的 id（task 层赋值）
```

---

### 8.4 task 层改动

`backend/app/tasks/autofix_task.py`：

**a)** `_group_issues_by_range` 函数签名扩展返回值：

```python
def _group_issues_by_range(
    db_issues: Iterable[Issue],
) -> tuple[list[IssueRef], dict[str, list[str]], str]:
    """新增第 3 个返回值：global_rep_id（所有 issue 里 severity 最高那条的 id），
    供 final patch 使用。
    """
    # 现有逻辑不变...
    # 末尾：
    
    # 选 global representative：所有 db_issues 里 severity 最高那条
    all_sorted = sorted(
        db_issues,
        key=lambda x: _SEVERITY_ORDER.get(getattr(x.severity, "value", x.severity), 99),
    )
    global_rep_id = str(all_sorted[0].id) if all_sorted else ""
    
    return issue_refs, representative_ids, global_rep_id
```

**b)** `run_autofix_task` 注入 `final_rep_id` 并处理 final patch 写入：

```python
issue_refs, representative_ids, global_rep_id = _group_issues_by_range(db_issues)

initial: AutoFixState = {
    "review_id": review_id,
    "source_code": review.source_code,
    "language": review.language or "python",
    "issues": issue_refs,
    "patches": [],
    "error": None,
    "final_rep_id": global_rep_id,
}

# ... graph.ainvoke ...

patches: list[PatchOutput] = final_state.get("patches", []) or []
issue_by_id = {str(i.id): i for i in db_issues}

for p in patches:
    db.add(Patch(
        review_id=uid,
        issue_id=uuid.UUID(p.issue_id),
        original_code=p.original_code,
        fixed_code=p.fixed_code,
        diff=p.diff,
        syntax_valid=p.syntax_valid,
        error_msg=p.error_msg,
        status=p.status,
        is_final=p.is_final,   # ← 新增
    ))
    # final patch 不参与 issues.fixed 标记（避免重复打 True）
    if p.is_final:
        continue
    if p.status == PatchStatus.done and p.syntax_valid:
        for member_id in representative_ids.get(p.issue_id, [p.issue_id]):
            if member_id in issue_by_id:
                issue_by_id[member_id].fixed = True
```

---

### 8.5 API 返回字段

`backend/app/api/v1/patches.py:PatchResponse` 加字段：

```python
class PatchResponse(BaseModel):
    # ...existing fields...
    is_final: bool
```

`list_patches` 路由的 list comprehension 也要加 `is_final=p.is_final`。

**响应排序**：当前是 `ORDER BY created_at ASC`，由于 final patch 是最后写入的，会在列表末尾。为前端方便突出展示，**改成 `is_final DESC, created_at ASC`**：

```python
result = await db.execute(
    select(Patch)
    .where(Patch.review_id == uid)
    .order_by(Patch.is_final.desc(), Patch.created_at.asc())
)
```

---

### 8.6 前端展示

`frontend/src/lib/types.ts:Patch` 加字段：

```ts
export interface Patch {
  // ...existing fields...
  is_final: boolean
}
```

`frontend/src/components/PatchPanel.tsx` 拆分渲染：

```tsx
const finalPatch = patches.find(p => p.is_final && p.status === 'done')
const perIssuePatches = patches.filter(p => !p.is_final)

return (
  <div className="flex flex-col h-full gap-3 overflow-hidden">
    {/* 顶部触发栏不变 */}
    
    {/* 新增：FinalPatchCard 突出展示在最顶部 */}
    {finalPatch && (
      <FinalPatchCard patch={finalPatch} language={language} />
    )}
    
    {/* per-issue patch 列表 */}
    {perIssuePatches.length === 0 ? (
      // 空态
    ) : (
      <div className="flex-1 flex flex-col gap-3 overflow-y-auto pr-1">
        {!finalPatch && polling && <p className="text-xs text-slate-500">正在生成综合修复版…</p>}
        <p className="text-xs text-slate-500 uppercase tracking-wider mt-2">单 issue 修复</p>
        {perIssuePatches.map(p => <PatchCard key={p.id} patch={p} language={language} />)}
      </div>
    )}
  </div>
)
```

`FinalPatchCard` 组件新建（同文件内）：

```tsx
function FinalPatchCard({ patch, language }: { patch: Patch; language: string }) {
  const [copied, setCopied] = useState(false)
  
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(patch.fixed_code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {}
  }
  
  const handleDownload = () => {
    const ext = LANG_EXT[language.toLowerCase()] ?? 'txt'
    const blob = new Blob([patch.fixed_code], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `final-fixed.${ext}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 1000)   // 同 #7
  }
  
  return (
    <div className="bg-gradient-to-br from-indigo-900/40 to-slate-900 border-2 border-indigo-500/60 rounded-lg overflow-hidden shrink-0">
      <div className="flex items-center gap-3 px-4 py-3 bg-indigo-900/30 border-b border-indigo-500/40">
        <span className="text-lg">✨</span>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-indigo-200">最终修复版（综合所有 issue）</h3>
          <p className="text-xs text-indigo-300/70">已修复全部 {/* total issues count if available */} 个问题，开箱即用</p>
        </div>
        <button
          onClick={handleCopy}
          className="px-3 py-1.5 rounded text-sm bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
        >
          {copied ? '✓ 已复制' : '📋 复制完整代码'}
        </button>
        <button
          onClick={handleDownload}
          className="px-3 py-1.5 rounded text-sm bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
        >
          ⬇ 下载
        </button>
      </div>
      <CodeDiffViewer
        original={patch.original_code}
        modified={patch.fixed_code}
        language={language}
        height="320px"
      />
    </div>
  )
}
```

---

### 8.7 测试

**单元测试 backend/tests/unit/test_autofix_final_prompt.py**：
- prompt 包含全部 issue description
- prompt 包含全部 suggestion（如果有）
- 空 suggestion 显示 fallback 文案

**集成测试 backend/tests/integration/test_autofix_final.py**：
- monkeypatch graph，让 `merge_all_node` 同样产出受控 PatchOutput
- 跑完后 patches 表里应当有 N+1 条（N 个 per-issue + 1 个 final）
- 这个 final patch `is_final=True`
- final patch 不影响 issues.fixed 的标记（仅 per-issue patch 影响）

**API 测试**：list_patches 返回的 `is_final=True` 的 patch 应当排在最前面。

---

## #6–#8 验收脚本（架构会话用）

```powershell
# 1. 跑迁移
cd F:/Code/Claude_Code/codessentinel/backend
./venv/Scripts/python.exe -m alembic upgrade head

# 2. 单元 + 集成
$env:TEST_DATABASE_URL = "postgresql+asyncpg://codessentinel:codessentinel@localhost:5432/codessentinel_test"
./venv/Scripts/python.exe -m pytest tests/ -v

# 3. tsc
cd ../frontend
npx tsc --noEmit

# 4. 部署
cd ..
docker compose restart worker      # ⚠️ 必须！worker 不热加载
docker compose restart backend     # 让新 schema 字段被 ORM 看见
# frontend vite 自动热重载，不用 restart
```

---

## 关键工程教训（请记住）

1. **ARQ worker 不热加载** —— 改 `app/tasks/` 下任何文件后必须 `docker compose restart worker`。集成测试通过 ≠ 容器内代码已生效。
2. **uvicorn --reload 也不一定热加载新模块** —— 改 ORM 模型 / 加新字段后建议 restart backend。
3. **alembic 迁移要在 prod 库和 test 库都跑** —— `codessentinel` 和 `codessentinel_test` 两个 DB。

---

## 不要做的事

- ❌ 不要把 `patches.issue_id` 改成 nullable（保持现有约束，final patch 用 global_rep_id 占位）
- ❌ 不要让 final patch 也影响 issues.fixed（避免重复标记）
- ❌ 不要在 trigger 接口里加同步跑 LLM 的逻辑（保持 trigger 入队就返回的语义）
- ❌ 不要 squash push 到 main，只 push `fix/autofix-ux-v0.4.2`

---

## 完工后报告格式

```
## v0.4.2 完成报告（v2 含 #6/#7/#8）

### 文件变更
- backend/app/api/v1/patches.py：#6 trigger 同步 DELETE + is_final 排序 + PatchResponse 字段
- backend/app/agents/autofix_agent.py：merge_all_node + PatchOutput.is_final
- backend/app/agents/prompts.py：AUTOFIX_FINAL_SYSTEM_PROMPT + build_autofix_final_prompt
- backend/app/models/patch.py：is_final 字段
- backend/app/tasks/autofix_task.py：_group_issues_by_range 返回 global_rep_id；写入时 is_final 区分处理
- backend/alembic/versions/0003_add_patch_is_final.py：新建迁移
- frontend/src/components/PatchPanel.tsx：FinalPatchCard + #7 revoke 延后
- frontend/src/lib/types.ts：Patch.is_final
- backend/tests/integration/test_autofix_trigger_clears.py：#6 race fix 测试
- backend/tests/integration/test_autofix_final.py：#8 final patch 测试
- backend/tests/unit/test_autofix_final_prompt.py：prompt 单测

### 测试结果
- 单元：X passed
- 集成：Y passed
- tsc：零错误
- 已 docker compose restart worker + backend，alembic upgrade head 已跑

### 已知遗留
- conftest.py:23 DB user 拼写仍为 codesentinel（v0.4.3 修）
```

架构和测试会话拿到报告会做：审查 → 跑全套测试 → Playwright 验证三个修复 → merge --no-ff → tag v0.4.2 → push main + tag。
