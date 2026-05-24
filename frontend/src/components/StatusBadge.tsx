import type { IssueSeverity, ReviewStatus } from '../lib/types'

const statusStyles: Record<ReviewStatus, string> = {
  pending:  'bg-slate-700 text-slate-300',
  running:  'bg-blue-900  text-blue-300  animate-pulse',
  done:     'bg-green-900 text-green-300',
  failed:   'bg-red-900   text-red-300',
}

const statusLabels: Record<ReviewStatus, string> = {
  pending: '⏳ 等待中',
  running: '⚡ 审查中',
  done:    '✅ 完成',
  failed:  '❌ 失败',
}

export function StatusBadge({ status }: { status: ReviewStatus }) {
  return (
    <span className={`text-xs px-2 py-1 rounded-full font-medium ${statusStyles[status]}`}>
      {statusLabels[status]}
    </span>
  )
}

// ── Severity Badge ────────────────────────────────────────────────────────────

const severityStyles: Record<IssueSeverity, string> = {
  critical:   'bg-red-900    text-red-300',
  warning:    'bg-yellow-900 text-yellow-300',
  suggestion: 'bg-blue-900   text-blue-300',
}

const severityIcons: Record<IssueSeverity, string> = {
  critical:   '🔴',
  warning:    '🟡',
  suggestion: '💡',
}

export function SeverityBadge({ severity }: { severity: IssueSeverity }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-medium ${severityStyles[severity]}`}>
      {severityIcons[severity]} {severity}
    </span>
  )
}
