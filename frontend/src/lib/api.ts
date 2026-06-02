import axios from 'axios'
import type { PatchListResponse, Review } from './types'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

const http = axios.create({
  baseURL: `${API_BASE}/api/v1`,
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

export const patchesApi = {
  trigger: (reviewId: string) =>
    http.post<{ review_id: string; status: string }>(`/reviews/${reviewId}/autofix`),

  list: (reviewId: string) =>
    http.get<PatchListResponse>(`/reviews/${reviewId}/patches`),
}

export interface Repository {
  id: string
  platform: 'github' | 'gitlab' | 'gitee'
  url: string
  indexed_at: string | null
}

export const repositoryApi = {
  list: () => http.get<Repository[]>('/repositories'),
  create: (payload: { platform: string; url: string }) =>
    http.post<Repository>('/repositories', payload),
  delete: (id: string) => http.delete(`/repositories/${id}`),
  triggerIndex: (id: string) =>
    http.post<{ status: string; repository_id: string }>(`/repositories/${id}/index`),
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

export const WS_BASE = import.meta.env.VITE_WS_URL ?? API_BASE
