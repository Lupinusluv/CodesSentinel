import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { reviewApi } from '../lib/api'
import type { Review } from '../lib/types'
import { ReviewCard } from '../components/ReviewCard'

export function Dashboard() {
  const [reviews, setReviews] = useState<Review[]>([])
  const [loading, setLoading]  = useState(true)
  const [error, setError]      = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    reviewApi.list()
      .then(res  => setReviews(res.data))
      .catch(()  => setError('无法加载审查历史，请确认后端服务是否运行'))
      .finally(() => setLoading(false))
  }, [])

  const criticalCount = reviews.flatMap(r => r.issues).filter(i => i.severity === 'critical').length
  const doneCount     = reviews.filter(r => r.status === 'done').length

  return (
    <div className="flex-1 flex flex-col overflow-hidden p-6 gap-4">
      {/* Stats row */}
      <div className="flex gap-4 shrink-0">
        {[
          { label: '审查总数',  value: reviews.length },
          { label: '已完成',    value: doneCount       },
          { label: '严重问题',  value: criticalCount, warn: criticalCount > 0 },
        ].map(stat => (
          <div
            key={stat.label}
            className={`flex-1 rounded-lg border p-4 ${
              stat.warn ? 'bg-red-950 border-red-800' : 'bg-slate-900 border-slate-700'
            }`}
          >
            <p className="text-2xl font-bold text-white">{stat.value}</p>
            <p className="text-xs text-slate-400 mt-1">{stat.label}</p>
          </div>
        ))}

        <button
          onClick={() => navigate('/')}
          className="px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-medium transition-colors self-center"
        >
          + 新建审查
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-2">
        {loading && (
          <div className="flex items-center justify-center h-full text-slate-400">
            加载中…
          </div>
        )}

        {error && (
          <div className="rounded-lg bg-red-950 border border-red-800 text-red-300 text-sm px-4 py-3">
            {error}
          </div>
        )}

        {!loading && !error && reviews.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
            <span className="text-4xl">📭</span>
            <p>暂无审查记录，<button onClick={() => navigate('/')} className="text-indigo-400 underline">开始第一次审查</button></p>
          </div>
        )}

        {reviews.map(review => (
          <ReviewCard key={review.id} review={review} />
        ))}
      </div>
    </div>
  )
}
