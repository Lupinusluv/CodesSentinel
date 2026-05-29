# v0.4.4 工作交接 — i18n 中英切换

**前提**：v0.4.3 已 ship（tag v0.4.3 在 main 上）。本版本在新分支 `feat/v0.4.4-i18n` 上做。

---

## 范围

把前端 UI 的 86 处中文字符串改造为可在 **中 / EN** 之间切换的国际化版本。

**不引入 react-i18next**——字符串少（86 条），自己写 Context + 字典（约 80 行核心代码）。面试时可作为加分点讲："为啥不引入 i18next"。

业务文本（LLM 生成的 issue.description / suggestion / report_text、后端错误 detail）**不在本轮范围**——它们是动态内容，需要 prompt 工程改造，留到 v0.5.x 一起做。

---

## 文件清单

### 新建（2 个）

| 文件 | 内容 |
|---|---|
| `frontend/src/i18n/strings.ts` | 字典 + Lang/StringKey 类型 |
| `frontend/src/i18n/LanguageContext.tsx` | Provider + useT hook + localStorage 持久化 |

### 修改（12 个）

| 文件 | 改动 |
|---|---|
| `frontend/src/main.tsx` | `<App />` 外包 `<LanguageProvider>` |
| `frontend/src/components/Layout.tsx`（或 App.tsx，看 banner 在哪） | header 加 EN/中 toggle |
| `frontend/src/pages/NewReview.tsx` | 4 处中文 → `t('newReview.xxx')` |
| `frontend/src/pages/Dashboard.tsx` | 7 处 |
| `frontend/src/pages/ReviewDetail.tsx` | 8 处 |
| `frontend/src/pages/Repositories.tsx` | 14 处 |
| `frontend/src/pages/Metrics.tsx` | 10 处 |
| `frontend/src/components/PatchPanel.tsx` | 29 处（含 FinalPatchCard） |
| `frontend/src/components/IssueList.tsx` | 5 处 |
| `frontend/src/components/StatusBadge.tsx` | 4 处 |
| `frontend/src/components/StreamOutput.tsx` | 2 处 |
| `frontend/src/hooks/useReview.ts` | 3 处（如有错误提示文案） |

---

## 设计：核心代码

### `i18n/strings.ts`

```ts
export type Lang = 'zh' | 'en'

export const strings = {
  zh: {
    // nav
    'nav.newReview': '🔍 新建审查',
    'nav.history': '📋 历史',
    'nav.repos': '🗂 仓库',
    'nav.metrics': '📊 指标',
    'nav.langToggle': 'EN',  // 当前是 zh，按钮显示切换目标
    // common
    'common.loading': '加载中…',
    'common.empty': '暂无数据',
    'common.failed': '加载失败',
    'common.copy': '📋 复制',
    'common.copied': '✓ 已复制',
    'common.download': '⬇ 下载',
    'common.cancel': '取消',
    'common.back': '← 返回',
    // newReview
    'newReview.lang': '语言',
    'newReview.placeholder': '# 粘贴你的代码片段，点击"开始审查"\n...',
    'newReview.start': '开始审查',
    'newReview.streamingHint': '审查结果将在此实时显示...',
    // patch (FinalPatchCard + PatchCard)
    'patch.autoFix': 'Auto Fix',
    'patch.generating': '生成中…',
    'patch.submitting': '提交中…',
    'patch.polling': '· 轮询中',
    'patch.notReady': '审查未完成，无法触发 AutoFix',
    'patch.noIssues': '没有 issue，无需修复',
    'patch.hint': '点击 Auto Fix 为所有 issue 生成修复建议',
    'patch.generatingPatches': '正在生成 patches…',
    'patch.generatingFinal': '正在生成综合修复版…',
    'patch.perIssue': '单 issue 修复',
    'patch.finalTitle': '最终修复版（综合所有 issue）',
    'patch.finalSubtitle': '已修复全部 {n} 个问题，开箱即用',
    'patch.copyFull': '📋 复制完整代码',
    // ... 全部 86 个 key
  },
  en: {
    'nav.newReview': '🔍 New Review',
    'nav.history': '📋 History',
    'nav.repos': '🗂 Repos',
    'nav.metrics': '📊 Metrics',
    'nav.langToggle': '中',
    'common.loading': 'Loading…',
    'common.empty': 'No data',
    'common.failed': 'Failed to load',
    'common.copy': '📋 Copy',
    'common.copied': '✓ Copied',
    'common.download': '⬇ Download',
    'common.cancel': 'Cancel',
    'common.back': '← Back',
    'newReview.lang': 'Language',
    'newReview.placeholder': '# Paste your code, then click "Review"\n...',
    'newReview.start': 'Review',
    'newReview.streamingHint': 'Review results will appear here in real time...',
    'patch.autoFix': 'Auto Fix',
    'patch.generating': 'Generating…',
    'patch.submitting': 'Submitting…',
    'patch.polling': '· Polling',
    'patch.notReady': 'Review not finished, AutoFix unavailable',
    'patch.noIssues': 'No issues to fix',
    'patch.hint': 'Click Auto Fix to generate patches for all issues',
    'patch.generatingPatches': 'Generating patches…',
    'patch.generatingFinal': 'Generating consolidated fix…',
    'patch.perIssue': 'Per-issue fixes',
    'patch.finalTitle': 'Consolidated Fix (all issues)',
    'patch.finalSubtitle': 'All {n} issues fixed, ready to use',
    'patch.copyFull': '📋 Copy full code',
    // ... 对应的英文
  },
} as const

export type StringKey = keyof typeof strings.zh
```

### `i18n/LanguageContext.tsx`

```tsx
import { createContext, useContext, useState, type ReactNode } from 'react'
import { strings, type Lang, type StringKey } from './strings'

interface Ctx {
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: StringKey, vars?: Record<string, string | number>) => string
}

const LangCtx = createContext<Ctx | null>(null)

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const saved = localStorage.getItem('cs-lang')
    return saved === 'en' || saved === 'zh' ? saved : 'zh'
  })

  const setLang = (l: Lang) => {
    setLangState(l)
    localStorage.setItem('cs-lang', l)
  }

  // 简单 {n} 占位替换；不引入 ICU MessageFormat
  const t = (key: StringKey, vars?: Record<string, string | number>) => {
    const tpl = strings[lang][key] || key
    if (!vars) return tpl
    return tpl.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? `{${k}}`))
  }

  return <LangCtx.Provider value={{ lang, setLang, t }}>{children}</LangCtx.Provider>
}

export function useT() {
  const ctx = useContext(LangCtx)
  if (!ctx) throw new Error('useT must be used inside <LanguageProvider>')
  return ctx
}
```

### Layout 切换按钮

在 header 现有导航旁加一个：

```tsx
const { lang, setLang, t } = useT()

<button
  onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
  className="px-2 py-1 text-xs rounded border border-slate-700 text-slate-300 hover:bg-slate-800"
  title={lang === 'zh' ? 'Switch to English' : '切换到中文'}
>
  {t('nav.langToggle')}
</button>
```

### 调用方示例（FinalPatchCard）

```tsx
const { t } = useT()
// 替换前
<h3>最终修复版（综合所有 issue）</h3>
<p>已修复全部 {totalIssues} 个问题，开箱即用</p>
<button>📋 复制完整代码</button>

// 替换后
<h3>{t('patch.finalTitle')}</h3>
<p>{t('patch.finalSubtitle', { n: totalIssues })}</p>
<button>{copied ? t('common.copied') : t('patch.copyFull')}</button>
```

---

## 实施步骤建议

1. **先建骨架**：strings.ts（先放空字典）+ LanguageContext.tsx + main.tsx 包 Provider + Layout 加按钮 + 验证 toggle 能切（即使没字符串）
2. **逐文件迁移**：按工作量从小到大：
   - StreamOutput (2) → useReview (3) → StatusBadge (4) → IssueList (5) → NewReview (4) → Dashboard (7) → ReviewDetail (8) → Metrics (10) → Repositories (14) → PatchPanel (29)
3. **每迁完一个文件跑 tsc**，StringKey 类型会立刻报"未定义的 key"，反向驱动你补字典
4. **最后扫一遍**：`grep -P '[\\p{Han}]' src/` 应该只剩 placeholder、JSDoc、注释中的中文

---

## 翻译质量约定

- **UI 术语保持简洁**：Review / Issue / Patch 不翻译（行业通用）
- **emoji 中英共用**：📋 ⬇ ✨ 🔴 🟡 💡 在两语言版本里一致
- **占位符 `{n}` 用 `t('key', { n: value })` 传入**，不要拼字符串

---

## 验收（架构会话做）

1. **tsc 必须零错误** —— StringKey 类型确保所有 key 在两种语言下都存在；如果某 key 只加了 zh 没加 en（或反之），编译会失败
2. **Playwright**：
   - 点 EN → header 全部英文、PatchPanel 全部英文、FinalPatchCard 文案变 "All 7 issues fixed, ready to use"
   - 切回 中 → 全部恢复中文
   - reload → 语言保持（localStorage）
3. **人眼**：滚动 5 个页面，中文 / 英文模式下不应残留另一语言的字面量（除了 LLM 生成的业务文本）

## 已知不在本轮范围

- issue.description / suggestion / report_text（LLM 输出）
- 后端 error detail（FastAPI HTTPException 中文消息）
- `eval_data/` 评测样本的中文标注

这些可以面试时主动说："前端 UI 国际化做了，业务文本是 LLM 输出，可扩展。"

## 工程量

约 **2-2.5 小时**。其中翻译 ~30 分钟，字符串替换 ~45 分钟（一个个改），剩下做骨架和验收。
