export type IssueCategory = 'security' | 'performance' | 'style'
export type IssueSeverity = 'critical' | 'warning' | 'suggestion'
export type ReviewStatus = 'pending' | 'running' | 'done' | 'failed'

export interface Issue {
  id: string
  category: IssueCategory
  severity: IssueSeverity
  line_start: number | null
  line_end: number | null
  description: string
  suggestion: string | null
  fixed: boolean
}

export interface Review {
  id: string
  status: ReviewStatus
  language: string | null
  total_issues: number
  duration_ms: number | null
  created_at: string
  report_text: string | null
  issues: Issue[]
}

export type StreamMessage =
  | { type: 'token'; content: string }
  | { type: 'done'; issue_count: number; duration_ms: number }
  | { type: 'error'; message: string }
  | { type: 'info'; message: string }
