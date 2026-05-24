import { useNavigate } from 'react-router-dom'
import type { Review } from '../lib/types'
import { StatusBadge } from './StatusBadge'

interface ReviewCardProps {
  review: Review
}

const categoryColors: Record<string, string> = {
  security:    'bg-red-900 text-red-300',
  performance: 'bg-yellow-900 text-yellow-300',
  style:       'bg-blue-900 text-blue-300',
}

export function ReviewCard({ review }: ReviewCardProps) {
  const navigate = useNavigate()

  const categoryCounts = review.issues.reduce<Record<string, number>>((acc, issue) => {
    acc[issue.category] = (acc[issue.category] ?? 0) + 1
    return acc
  }, {})

  const formattedDate = new Date(review.created_at).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit',  minute: '2-digit',
  })

  return (
    <div
      onClick={() => navigate(`/review/${review.id}`)}
      className="bg-slate-900 border border-slate-700 rounded-lg p-4 hover:border-slate-500 hover:bg-slate-800 transition-colors cursor-pointer"
    >
      <div className="flex items-center gap-3 mb-2">
        <StatusBadge status={review.status} />
        {review.language && (
          <span className="text-xs font-mono text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
            {review.language}
          </span>
        )}
        <span className="text-xs text-slate-500 ml-auto">{formattedDate}</span>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {review.total_issues > 0 ? (
          <>
            <span className="text-sm text-slate-300">{review.total_issues} issues</span>
            {Object.entries(categoryCounts).map(([cat, count]) => (
              <span
                key={cat}
                className={`text-xs px-1.5 py-0.5 rounded ${categoryColors[cat] ?? 'bg-slate-700 text-slate-300'}`}
              >
                {cat} {count}
              </span>
            ))}
          </>
        ) : (
          <span className="text-sm text-slate-500">
            {review.status === 'done' ? '✅ No issues found' : '—'}
          </span>
        )}

        {review.duration_ms && (
          <span className="text-xs text-slate-500 ml-auto">
            {(review.duration_ms / 1000).toFixed(1)}s
          </span>
        )}
      </div>
    </div>
  )
}
