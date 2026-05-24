import { useEffect, useRef, useState } from 'react'
import { reviewApi, WS_BASE } from '../lib/api'
import type { Review, StreamMessage } from '../lib/types'

export type ReviewPhase = 'idle' | 'submitting' | 'streaming' | 'done' | 'error'

export function useReview() {
  const [phase, setPhase] = useState<ReviewPhase>('idle')
  const [reviewId, setReviewId] = useState<string | null>(null)
  const [streamText, setStreamText] = useState('')
  const [review, setReview] = useState<Review | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const wsRef = useRef<WebSocket | null>(null)

  // 组件卸载时关闭 WebSocket
  useEffect(() => () => wsRef.current?.close(), [])

  const startReview = async (sourceCode: string, language: string) => {
    // 重置状态，关闭上一次的连接
    wsRef.current?.close()
    wsRef.current = null
    setStreamText('')
    setReview(null)
    setErrorMsg('')
    setPhase('submitting')

    try {
      const { data } = await reviewApi.create(sourceCode, language)
      const id = data.review_id
      setReviewId(id)
      setPhase('streaming')

      const ws = new WebSocket(`${WS_BASE}/ws/${id}`)
      wsRef.current = ws

      ws.onmessage = (event: MessageEvent) => {
        const msg: StreamMessage = JSON.parse(event.data as string)

        if (msg.type === 'token') {
          setStreamText(prev => prev + msg.content)
        } else if (msg.type === 'done') {
          // 拉取结构化结果（含 issues 列表）
          reviewApi.get(id).then(res => {
            setReview(res.data)
            setPhase('done')
          })
        } else if (msg.type === 'error') {
          setErrorMsg(msg.message)
          setPhase('error')
        }
      }

      ws.onerror = () => {
        setErrorMsg('WebSocket 连接失败，请检查后端服务是否运行')
        setPhase('error')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '请求失败'
      setErrorMsg(msg)
      setPhase('error')
    }
  }

  return { phase, reviewId, streamText, review, errorMsg, startReview }
}
