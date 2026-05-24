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

export const WS_BASE = 'ws://localhost:8000'
