import type { Issue, IssueSeverity } from '../lib/types'
import { SeverityBadge } from './StatusBadge'

const SEVERITY_ORDER: IssueSeverity[] = ['critical', 'warning', 'suggestion']

const categoryLabel: Record<string, string> = {
  security:    '🔒 Security',
  performance: '⚡ Performance',
  style:       '✏️ Style',
}

interface IssueListProps {
  issues: Issue[]
  durationMs: number | null
}

export function IssueList({ issues, durationMs }: IssueListProps) {
  if (issues.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-2">
        <span className="text-4xl">✅</span>
        <p className="text-lg">未发现问题</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 overflow-y-auto h-full pr-1">
      {/* 摘要行 */}
      <div className="flex items-center justify-between text-sm text-slate-400 pb-2 border-b border-slate-700">
        <span>共 {issues.length} 个问题</span>
        {durationMs && <span>耗时 {(durationMs / 1000).toFixed(1)}s</span>}
      </div>

      {/* 按 severity 分组 */}
      {SEVERITY_ORDER.map(severity => {
        const group = issues.filter(i => i.severity === severity)
        if (!group.length) return null
        return (
          <section key={severity}>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
              {severity} ({group.length})
            </h3>
            <div className="flex flex-col gap-2">
              {group.map(issue => (
                <IssueCard key={issue.id} issue={issue} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function IssueCard({ issue }: { issue: Issue }) {
  const lineInfo = issue.line_start
    ? `L${issue.line_start}${issue.line_end && issue.line_end !== issue.line_start ? `–${issue.line_end}` : ''}`
    : null

  return (
    <div className="bg-slate-900 rounded-lg p-3 border border-slate-700 hover:border-slate-500 transition-colors">
      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
        <SeverityBadge severity={issue.severity} />
        <span className="text-xs text-slate-500">{categoryLabel[issue.category] ?? issue.category}</span>
        {lineInfo && (
          <span className="text-xs font-mono text-slate-500 ml-auto">{lineInfo}</span>
        )}
      </div>
      <p className="text-sm text-slate-200 leading-snug">{issue.description}</p>
      {issue.suggestion && (
        <p className="text-xs text-slate-400 mt-1.5 pl-2 border-l-2 border-slate-600">
          {issue.suggestion}
        </p>
      )}
    </div>
  )
}
