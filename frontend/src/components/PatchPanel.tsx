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
      if (fresh && fresh.length >= totalIssues && fresh.every(p => p.status !== 'pending')) {
        stopPolling()
      } else if (elapsed > POLL_MAX_MS) {
        stopPolling()
      }
    }, POLL_INTERVAL_MS)
  }, [fetchPatches, stopPolling, totalIssues])

  const handleTrigger = async () => {
    if (triggering || polling) return
    setTrig(true)
    setError(null)
    try {
      await patchesApi.trigger(reviewId)
      // 后台异步生成，立刻开轮询
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
          {patches.length} / {totalIssues} patches
          {polling && ' · 轮询中'}
        </span>
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>

      {patches.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
          {reviewStatus !== 'done' ? (
            <p className="text-sm">审查未完成，无法触发 AutoFix</p>
          ) : totalIssues === 0 ? (
            <p className="text-sm">没有 issue，无需修复</p>
          ) : (
            <p className="text-sm">点击 Auto Fix 为所有 issue 生成修复建议</p>
          )}
        </div>
      ) : (
        <div className="flex-1 flex flex-col gap-3 overflow-y-auto pr-1">
          {patches.map(p => (
            <PatchCard key={p.id} patch={p} language={language} />
          ))}
        </div>
      )}
    </div>
  )
}

function PatchCard({ patch, language }: { patch: Patch; language: string }) {
  const statusColor =
    patch.status === 'done'    ? 'text-green-400 border-green-700/50' :
    patch.status === 'failed'  ? 'text-red-400 border-red-700/50'     :
                                 'text-amber-400 border-amber-700/50'

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
