import axios from 'axios'
import type { Review } from './types'

const http = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

export const reviewApi = {
  create: (source_code: string, language: string) =>
    http.post<{ review_id: string; status: string }>('/reviews', {
      source_code,
      language,
    }),

  get: (reviewId: string) => http.get<Review>(`/reviews/${reviewId}`),

  list: () => http.get<Review[]>('/reviews'),
}

export interface Repository {
  id: string
  platform: 'github' | 'gitlab' | 'gitee'
  url: string
  indexed_at: string | null
}

export const repositoryApi = {
  list: () => http.get<Repository[]>('/repositories'),
  create: (payload: { platform: string; url: string; webhook_secret: string }) =>
    http.post<Repository>('/repositories', payload),
  delete: (id: string) => http.delete(`/repositories/${id}`),
}

export interface MetricsSummary {
  total_reviews: number
  total_issues: number
  avg_duration_ms: number
  issues_by_category: Record<string, number>
  issues_by_severity: Record<string, number>
}

export const metricsApi = {
  summary: () => http.get<MetricsSummary>('/metrics'),
}

export const WS_BASE = 'ws://localhost:8000'
