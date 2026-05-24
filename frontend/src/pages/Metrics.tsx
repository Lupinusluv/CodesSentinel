import { useEffect, useState } from 'react'
import { metricsApi, type MetricsSummary } from '../lib/api'

const BAR_COLORS: Record<string, string> = {
  security:    'bg-red-500',
  performance: 'bg-yellow-500',
  style:       'bg-blue-500',
  critical:    'bg-red-500',
  warning:     'bg-yellow-500',
  suggestion:  'bg-blue-500',
}

function BarChart({ data, label }: { data: Record<string, number>; label: string }) {
  const total = Object.values(data).reduce((a, b) => a + b, 0)
  if (total === 0) return <p className="text-slate-500 text-sm">暂无数据</p>

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-slate-400 font-medium uppercase tracking-wide">{label}</p>
      {Object.entries(data).map(([key, count]) => (
        <div key={key} className="flex items-center gap-3">
          <span className="text-xs text-slate-400 w-24 shrink-0">{key}</span>
          <div className="flex-1 bg-slate-800 rounded-full h-2">
            <div
              className={`h-2 rounded-full ${BAR_COLORS[key] ?? 'bg-slate-500'}`}
              style={{ width: `${(count / total) * 100}%` }}
            />
          </div>
          <span className="text-xs text-slate-400 w-8 text-right">{count}</span>
        </div>
      ))}
    </div>
  )
}

export function Metrics() {
  const [data, setData]       = useState<MetricsSummary | null>(null)
  const [error, setError]     = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    metricsApi.summary()
      .then(res  => setData(res.data))
      .catch(()  => setError('统计 API 尚未实现（后端返回 501）'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex-1 flex flex-col p-6 gap-6 overflow-auto">
      <h1 className="text-lg font-semibold text-white shrink-0">统计指标</h1>

      {loading && <p className="text-slate-400">加载中…</p>}

      {error && (
        <div className="rounded-lg bg-amber-950 border border-amber-700 px-4 py-3 text-amber-300 text-sm">
          {error}
          <p className="mt-1 text-xs opacity-70">
            指标功能在第 4 个月规划中实现，当前可在 Dashboard 页查看历史记录。
          </p>
        </div>
      )}

      {data && (
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: '审查总数',  value: data.total_reviews   },
            { label: '问题总数',  value: data.total_issues    },
            { label: '平均耗时',  value: `${(data.avg_duration_ms / 1000).toFixed(1)}s` },
          ].map(stat => (
            <div key={stat.label} className="bg-slate-900 border border-slate-700 rounded-lg p-4">
              <p className="text-2xl font-bold text-white">{stat.value}</p>
              <p className="text-xs text-slate-400 mt-1">{stat.label}</p>
            </div>
          ))}

          <div className="col-span-3 bg-slate-900 border border-slate-700 rounded-lg p-4 grid grid-cols-2 gap-6">
            <BarChart data={data.issues_by_category} label="按类别" />
            <BarChart data={data.issues_by_severity} label="按严重级别" />
          </div>
        </div>
      )}
    </div>
  )
}
