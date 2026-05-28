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
  source_code?: string | null
  issues: Issue[]
}

export type PatchStatus = 'pending' | 'done' | 'failed'

export interface Patch {
  id: string
  review_id: string
  issue_id: string
  original_code: string
  fixed_code: string
  diff: string
  syntax_valid: boolean
  error_msg: string | null
  status: PatchStatus
  is_final: boolean
  created_at: string
}

export interface PatchListResponse {
  review_id: string
  total: number
  patches: Patch[]
}

export type AgentName = 'security' | 'performance' | 'style' | 'synthesis'

export type StreamMessage =
  | { type: 'token';            content: string }
  | { type: 'agent_start';      agent: AgentName }
  | { type: 'agent_done';       agent: AgentName; issue_count: number }
  | { type: 'synthesis_token';  content: string }
  | { type: 'done';             issue_count: number; duration_ms: number }
  | { type: 'error';            message: string }
  | { type: 'info';             message: string }
