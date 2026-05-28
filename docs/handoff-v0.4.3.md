# v0.4.3 工作交接 — 下载自选目录 + 卫生项

**架构方：** v0.4.2 已 ship（main @ e464c9b，tag v0.4.2 已推送）。v0.4.3 在新分支 `chore/v0.4.3-polish` 上做。

---

## 范围（按优先级）

| # | 项 | 工程量 | 备注 |
|---|---|---|---|
| **#1** | 下载自选目录（File System Access API） | ~30 分钟 | **本版本主菜**，用户明确要求 |
| #2 | conftest 默认 DB user 拼写修正 | 1 行 | v0.4.2 时延期 |
| #3 | Monaco DiffEditor disposed unmount race | ~30 分钟 | v0.4.2 时延期 |

总预估 1.5 小时。

---

## #1 — 下载自选目录

### 现状

`frontend/src/components/PatchPanel.tsx` 第 37-47 行的 `downloadBlob`：
```ts
function downloadBlob(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
```

走的是 a.click 强制下载到浏览器默认目录，**用户无法选目录也无法改名**。

### 目标

点击 ⬇ 下载 → 弹出原生"另存为"对话框 → 用户可选目录、可改文件名。

### 方案

用 [`window.showSaveFilePicker`](https://developer.mozilla.org/en-US/docs/Web/API/Window/showSaveFilePicker) (File System Access API)，不支持的浏览器（Firefox / Safari）降级到原 a.click。

### 代码

替换 `downloadBlob` 为：

```ts
async function downloadBlob(content: string, filename: string) {
  // 优先用 File System Access API，让用户自选目录 + 改名
  // 仅 Chromium 系列（Chrome/Edge/Brave/Opera）支持
  if ('showSaveFilePicker' in window) {
    try {
      const handle = await (window as any).showSaveFilePicker({
        suggestedName: filename,
        types: [{
          description: 'Source file',
          accept: {
            'text/plain': ['.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.go', '.rs', '.cpp', '.c', '.txt'],
          },
        }],
      })
      const writable = await handle.createWritable()
      await writable.write(content)
      await writable.close()
      return
    } catch (e: any) {
      // 用户主动取消（AbortError）→ 静默退出，不降级
      // 否则强制走 a.click 会下载到默认位置，违反用户意图
      if (e?.name === 'AbortError') return
      // 其他错误（企业策略禁用 / 扩展拦截）→ 降级
      console.warn('showSaveFilePicker failed, falling back to <a download>:', e)
    }
  }

  // 降级：原 a.click 方案
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
```

### 调用方改动

`downloadBlob` 改成 `async`，两处调用点（PatchCard 和 FinalPatchCard 的 `handleDownload`）需要相应处理：

```ts
const handleDownload = () => {
  downloadBlob(patch.fixed_code, `fixed-${patch.issue_id.slice(0, 8)}.${extFor(language)}`)
  // 不 await 也 OK，promise rejection 已被 downloadBlob 内部处理
  // 但加 .catch(() => {}) 显式标注更稳，避免 lint 抱怨 unhandled promise
}
```

最佳写法：
```ts
const handleDownload = () => {
  void downloadBlob(patch.fixed_code, `fixed-${patch.issue_id.slice(0, 8)}.${extFor(language)}`)
}
```

`void` 比 `.catch(() => {})` 更明确表达"故意丢弃 promise"。

### 测试

- 单元 / 集成：**不加**。`showSaveFilePicker` 是浏览器原生 API，vitest jsdom 不支持，mock 出来没意义。
- TypeScript：`(window as any)` 已经绕开类型检查；不装 `@types/wicg-file-system-access`（依赖项越少越好）。
- tsc 必须零错误。

### 人眼验收（架构会话做）

1. Chromium：点 ⬇ 下载 → 弹"另存为"对话框 → 选个目录、改个名 → 确认 → 文件按选定路径保存
2. Chromium：点 ⬇ 下载 → 点对话框"取消" → **没有任何下载发生**（不能 fallback 到默认目录）
3. （可选）Firefox：点 ⬇ 下载 → 走 a.click 降级路径 → 文件按浏览器默认行为下载

---

## #2 — conftest 拼写修正

`backend/tests/conftest.py:21-24`：

```python
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://codesentinel:codesentinel@localhost:5432/codessentinel_test",
)
```

实际 docker-compose 里 PG user/password 都是 `codessentinel`（双 s）。改成：

```python
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://codessentinel:codessentinel@localhost:5432/codessentinel_test",
)
```

改完跑一次集成测试不带 env 覆盖：
```powershell
cd F:\Code\Claude_Code\codessentinel\backend
Remove-Item Env:\TEST_DATABASE_URL -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe -m pytest tests/integration/ -v -m integration
```

应该 24 passed。

---

## #3 — Monaco DiffEditor disposed unmount race

### 现象

`setPatches([])` 触发批量 unmount 时，控制台报 N 个：
```
Uncaught Error: TextModel got disposed before DiffEditorWidget model got reset
```

每个 PatchCard / FinalPatchCard 的 DiffEditor unmount 都触发一次。

### 根因

`@monaco-editor/react@^4.7.0` 在 React 19 + Strict Mode 下，DiffEditor unmount 时 TextModel 和 DiffEditorWidget 的销毁顺序有 race。这是 lib 已知问题，纯前端 lifecycle 配合不当。

### 方案选项（按推荐度）

**方案 A**（推荐）：升级 `@monaco-editor/react`，看新版本是否修了

```bash
cd frontend
npm install @monaco-editor/react@latest
npx tsc --noEmit
npm run dev  # 验证 errors 消失
```

如果升级后还在，转方案 B。

**方案 B**：用 `onMount` + cleanup 手动管理 dispose 顺序

修改 `frontend/src/components/CodeViewer.tsx`：
```tsx
import { useRef, useEffect } from 'react'
import Editor, { DiffEditor } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'

export function CodeDiffViewer({ original, modified, language = 'python', height = '400px' }: CodeDiffViewerProps) {
  const editorRef = useRef<editor.IStandaloneDiffEditor | null>(null)

  useEffect(() => {
    return () => {
      // unmount 时先 dispose widget，再让 lib 自然清理 model
      try {
        editorRef.current?.dispose()
      } catch {
        // 已被父组件清理
      }
    }
  }, [])

  return (
    <DiffEditor
      height={height}
      language={language}
      original={original}
      modified={modified}
      theme="vs-dark"
      onMount={(ed) => { editorRef.current = ed }}
      options={{ ...MONACO_OPTIONS, renderSideBySide: true }}
    />
  )
}
```

**方案 C**（如果 A/B 都不解决）：放弃，文档化"已知 console noise"，不阻塞 v0.4.3

### 验收

不再有 `TextModel got disposed before DiffEditorWidget model got reset` 报错。

---

## 完成报告模板

完工后开发会话给架构会话报：

```
v0.4.3 完成（chore/v0.4.3-polish）

变更：
- frontend/src/components/PatchPanel.tsx
  └ downloadBlob → async + showSaveFilePicker（降级 a.click）
- backend/tests/conftest.py
  └ user 拼写 codesentinel → codessentinel
- [视方案] frontend/package.json / CodeViewer.tsx
  └ @monaco-editor/react 升级 OR onMount cleanup

测试：
- 单元 50 passed（无新增）
- 集成 24 passed（不依赖 env 覆盖）
- tsc 零错误

未 commit，等架构验收。
```

架构会做：
1. Playwright 验下载对话框 + 取消行为
2. 集成测试不带 env 重跑
3. 浏览器看 console 是否还有 Monaco error
4. 全过 → 批准 commit + push → merge --no-ff → tag v0.4.3

---

## 工程提醒

- **不要**改 `setTimeout(() => URL.revokeObjectURL(url), 1000)` 在降级路径里的存在（v0.4.2 的 #7 修复）
- File System Access API 必须在用户手势内调用（onClick handler 已经满足，不用额外处理）
- conftest 改动后整套集成测试要重跑，**docker pg 必须在跑**
