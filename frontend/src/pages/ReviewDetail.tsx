import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { reviewApi } from '../lib/api'
import type { Review } from '../lib/types'
import { IssueList } from '../components/IssueList'
import { StatusBadge } from '../components/StatusBadge'
import { CodeViewer } from '../components/CodeViewer'

export function ReviewDetail() {
  const { reviewId } = useParams<{ reviewId: string }>()
  const navigate      = useNavigate()
  const [review, setReview]   = useState<Review | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [tab, setTab]         = useState<'issues' | 'code' | 'report'>('issues')

  useEffect(() => {
    if (!reviewId) return
    reviewApi.get(reviewId)
      .then(res  => setReview(res.data))
      .catch(()  => setError('无法加载审查记录'))
      .finally(() => setLoading(false))
  }, [reviewId])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400">加载中…</div>
    )
  }

  if (error || !review) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4">
        <p className="text-red-400">{error ?? '记录不存在'}</p>
        <button onClick={() => navigate('/dashboard')} className="text-indigo-400 underline text-sm">
          ← 返回历史
        </button>
      </div>
    )
  }

  const formattedDate = new Date(review.created_at).toLocaleString('zh-CN')

  return (
    <div className="flex-1 flex flex-col overflow-hidden p-6 gap-4">
      {/* Header */}
      <div className="flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-slate-400 hover:text-slate-200 text-sm"
        >
          ← 返回
        </button>
        <StatusBadge status={review.status} />
        {review.language && (
          <span className="text-xs font-mono text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
            {review.language}
          </span>
        )}
        <span className="text-xs text-slate-500">{formattedDate}</span>
        {review.duration_ms && (
          <span className="text-xs text-slate-500">
            · 耗时 {(review.duration_ms / 1000).toFixed(1)}s
          </span>
        )}
        <span className="text-xs text-slate-500">
          · {review.total_issues} issues
        </span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-800 shrink-0">
        {(['issues', 'code', 'report'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm transition-colors ${
              tab === t
                ? 'text-white border-b-2 border-indigo-500'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {t === 'issues' ? `Issues (${review.total_issues})`
             : t === 'code'   ? 'Source Code'
             : 'Report'}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {tab === 'issues' && (
          <IssueList issues={review.issues} durationMs={review.duration_ms} />
        )}

        {tab === 'code' && (
          review.source_code ? (
            <CodeViewer
              value={review.source_code}
              language={review.language ?? 'python'}
              height="100%"
            />
          ) : (
            <p className="text-slate-500 text-sm">源代码不可用（Webhook 触发的审查不存储 diff）</p>
          )
        )}

        {tab === 'report' && (
          <pre className="font-mono text-sm text-green-300 bg-slate-950 rounded-lg p-4 h-full overflow-y-auto whitespace-pre-wrap leading-relaxed">
            {review.report_text || <span className="text-slate-500 italic">无报告文本</span>}
          </pre>
        )}
      </div>
    </div>
  )
}
