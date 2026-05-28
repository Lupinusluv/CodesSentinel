import { useCallback, useEffect, useRef, useState } from 'react'
import { patchesApi } from '../lib/api'
import type { Patch, ReviewStatus } from '../lib/types'
import { CodeDiffViewer } from './CodeViewer'

interface PatchPanelProps {
  reviewId: string
  language: string
  reviewStatus: ReviewStatus
  totalIssues: number
}

const POLL_INTERVAL_MS = 2000
const POLL_MAX_MS = 120_000

// language → 下载文件扩展名映射，未识别落到 txt
const LANG_EXT: Record<string, string> = {
  python: 'py',
  py: 'py',
  javascript: 'js',
  js: 'js',
  typescript: 'ts',
  ts: 'ts',
  jsx: 'jsx',
  tsx: 'tsx',
  java: 'java',
  go: 'go',
  rust: 'rs',
}

function extFor(language: string): string {
  return LANG_EXT[language.toLowerCase()] ?? 'txt'
}

// 浏览器异步下载流程中，过早 revokeObjectURL 会导致 a.download 属性丢失，
// 文件名 fallback 成 blob URL 末尾的 UUID。延后 1s 让浏览器读完属性。
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

export function PatchPanel({ reviewId, language, reviewStatus, totalIssues }: PatchPanelProps) {
  const [patches, setPatches]   = useState<Patch[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)
  const [triggering, setTrig]   = useState(false)
  const [polling, setPolling]   = useState(false)
  const pollTimer    = useRef<number | null>(null)
  const pollStartRef = useRef<number>(0)

  const fetchPatches = useCallback(async () => {
    try {
      const res = await patchesApi.list(reviewId)
      setPatches(res.data.patches)
      setError(null)
      return res.data.patches
    } catch (e) {
      setError('加载 patches 失败')
      return null
    } finally {
      setLoading(false)
    }
  }, [reviewId])

  // 初次进入：拉一次看看是否已经存在 patches
  useEffect(() => {
    fetchPatches()
    return () => { if (pollTimer.current) window.clearInterval(pollTimer.current) }
  }, [fetchPatches])

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      window.clearInterval(pollTimer.current)
      pollTimer.current = null
    }
    setPolling(false)
  }, [])

  const startPolling = useCallback(() => {
    if (pollTimer.current) return
    pollStartRef.current = Date.now()
    setPolling(true)
    pollTimer.current = window.setInterval(async () => {
      const fresh = await fetchPatches()
      const elapsed = Date.now() - pollStartRef.current
      // 聚合后 patches 数 ≤ totalIssues，不能再用 length >= totalIssues 当停止条件
      if (fresh && fresh.length > 0 && fresh.every(p => p.status !== 'pending')) {
        stopPolling()
      } else if (elapsed > POLL_MAX_MS) {
        stopPolling()
      }
    }, POLL_INTERVAL_MS)
  }, [fetchPatches, stopPolling])

  const handleTrigger = async () => {
    if (triggering || polling) return
    setTrig(true)
    setError(null)
    try {
      await patchesApi.trigger(reviewId)
      // trigger 接口已同步 DELETE 旧 patches → 本地立刻清空，避免轮询拉到旧数据
      setPatches([])
      startPolling()
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? '触发失败'
      setError(typeof detail === 'string' ? detail : '触发失败')
    } finally {
      setTrig(false)
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-full text-slate-400">加载中…</div>
  }

  const canTrigger    = reviewStatus === 'done' && totalIssues > 0 && !polling && !triggering
  const triggerLabel  = polling ? '生成中…' : triggering ? '提交中…' : 'Auto Fix'

  const finalPatch     = patches.find(p => p.is_final && p.status === 'done')
  const perIssuePatches = patches.filter(p => !p.is_final)

  return (
    <div className="flex flex-col h-full gap-3 overflow-hidden">
      <div className="flex items-center gap-3 shrink-0">
        <button
          onClick={handleTrigger}
          disabled={!canTrigger}
          className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
            canTrigger
              ? 'bg-indigo-600 hover:bg-indigo-500 text-white'
              : 'bg-slate-700 text-slate-400 cursor-not-allowed'
          }`}
        >
          {triggerLabel}
        </button>
        <span className="text-xs text-slate-500">
          {patches.length} {patches.length === 1 ? 'patch' : 'patches'}
          {polling && ' · 轮询中'}
        </span>
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>

      {patches.length === 0 && !polling ? (
        <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
          {reviewStatus !== 'done' ? (
            <p className="text-sm">审查未完成，无法触发 AutoFix</p>
          ) : totalIssues === 0 ? (
            <p className="text-sm">没有 issue，无需修复</p>
          ) : (
            <p className="text-sm">点击 Auto Fix 为所有 issue 生成修复建议</p>
          )}
        </div>
      ) : patches.length === 0 && polling ? (
        <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
          <p className="text-sm">正在生成 patches…</p>
        </div>
      ) : (
        <div className="flex-1 flex flex-col gap-3 overflow-y-auto pr-1">
          {finalPatch && (
            <FinalPatchCard
              patch={finalPatch}
              language={language}
              totalIssues={totalIssues}
            />
          )}
          {!finalPatch && polling && (
            <p className="text-xs text-slate-500 italic">正在生成综合修复版…</p>
          )}
          {perIssuePatches.length > 0 && (
            <>
              <p className="text-xs text-slate-500 uppercase tracking-wider mt-1">
                单 issue 修复
              </p>
              {perIssuePatches.map(p => (
                <PatchCard key={p.id} patch={p} language={language} />
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function FinalPatchCard({
  patch, language, totalIssues,
}: { patch: Patch; language: string; totalIssues: number }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(patch.fixed_code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // 非 https / 无权限：静默失败，用户可手动选中
    }
  }

  const handleDownload = () => {
    downloadBlob(patch.fixed_code, `final-fixed.${extFor(language)}`)
  }

  return (
    <div className="bg-gradient-to-br from-indigo-900/40 to-slate-900 border-2 border-indigo-500/60 rounded-lg overflow-hidden shrink-0">
      <div className="flex items-center gap-3 px-4 py-3 bg-indigo-900/30 border-b border-indigo-500/40">
        <span className="text-lg">✨</span>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-indigo-200">
            最终修复版（综合所有 issue）
          </h3>
          <p className="text-xs text-indigo-300/70">
            已修复全部 {totalIssues} 个问题，开箱即用
          </p>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="px-3 py-1.5 rounded text-sm bg-indigo-600 hover:bg-indigo-500 text-white transition-colors shrink-0"
        >
          {copied ? '✓ 已复制' : '📋 复制完整代码'}
        </button>
        <button
          type="button"
          onClick={handleDownload}
          className="px-3 py-1.5 rounded text-sm bg-indigo-600 hover:bg-indigo-500 text-white transition-colors shrink-0"
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

function PatchCard({ patch, language }: { patch: Patch; language: string }) {
  const [copied, setCopied] = useState(false)
  const statusColor =
    patch.status === 'done'    ? 'text-green-400 border-green-700/50' :
    patch.status === 'failed'  ? 'text-red-400 border-red-700/50'     :
                                 'text-amber-400 border-amber-700/50'

  // failed 状态 fixed_code 可能为空字符串，此时隐藏按钮，避免界面噪音
  const canExport = Boolean(patch.fixed_code) && patch.status !== 'failed'

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(patch.fixed_code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // 非 https / 无权限时静默失败；用户可手动选中
    }
  }

  const handleDownload = () => {
    downloadBlob(patch.fixed_code, `fixed-${patch.issue_id.slice(0, 8)}.${extFor(language)}`)
  }

  return (
    <div className={`bg-slate-900 rounded-lg border ${statusColor.split(' ')[1]} overflow-hidden`}>
      <div className="flex items-center gap-2 px-3 py-2 bg-slate-800/50 border-b border-slate-700 text-xs">
        <span className={`uppercase font-semibold ${statusColor.split(' ')[0]}`}>{patch.status}</span>
        <span className="text-slate-500 font-mono">issue {patch.issue_id.slice(0, 8)}</span>
        {patch.syntax_valid
          ? <span className="text-slate-400">✓ syntax ok</span>
          : <span className="text-slate-400">✗ syntax invalid</span>}
        {patch.error_msg && (
          <span className="text-red-400 truncate" title={patch.error_msg}>
            · {patch.error_msg}
          </span>
        )}
        {canExport && (
          <div className="ml-auto flex gap-1">
            <button
              type="button"
              onClick={handleCopy}
              className="px-2 py-0.5 rounded text-slate-300 hover:bg-slate-700/70 hover:text-white transition-colors"
              title="复制修复后代码到剪贴板"
            >
              {copied ? '✓ 已复制' : '📋 复制'}
            </button>
            <button
              type="button"
              onClick={handleDownload}
              className="px-2 py-0.5 rounded text-slate-300 hover:bg-slate-700/70 hover:text-white transition-colors"
              title="下载修复后文件"
            >
              ⬇ 下载
            </button>
          </div>
        )}
      </div>
      {patch.original_code || patch.fixed_code ? (
        <CodeDiffViewer
          original={patch.original_code}
          modified={patch.fixed_code}
          language={language}
          height="240px"
        />
      ) : (
        <p className="p-3 text-xs text-slate-500 italic">No diff available</p>
      )}
    </div>
  )
}
