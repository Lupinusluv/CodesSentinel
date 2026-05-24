import { useEffect, useRef, useState } from 'react'
import { reviewApi, WS_BASE } from '../lib/api'
import type { AgentName, Review, StreamMessage } from '../lib/types'

export type ReviewPhase = 'idle' | 'submitting' | 'streaming' | 'done' | 'error'

export interface AgentStatus {
  status: 'pending' | 'running' | 'done'
  issueCount?: number
}

export function useReview() {
  const [phase, setPhase] = useState<ReviewPhase>('idle')
  const [reviewId, setReviewId] = useState<string | null>(null)
  const [streamText, setStreamText] = useState('')
  const [review, setReview] = useState<Review | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [agentStatuses, setAgentStatuses] = useState<Record<AgentName, AgentStatus>>({
    security:    { status: 'pending' },
    performance: { status: 'pending' },
    style:       { status: 'pending' },
    synthesis:   { status: 'pending' },
  })
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => () => wsRef.current?.close(), [])

  const resetAgentStatuses = () => setAgentStatuses({
    security:    { status: 'pending' },
    performance: { status: 'pending' },
    style:       { status: 'pending' },
    synthesis:   { status: 'pending' },
  })

  const startReview = async (sourceCode: string, language: string) => {
    wsRef.current?.close()
    wsRef.current = null
    setStreamText('')
    setReview(null)
    setErrorMsg('')
    resetAgentStatuses()
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

        if (msg.type === 'agent_start') {
          setAgentStatuses(prev => ({
            ...prev,
            [msg.agent]: { status: 'running' },
          }))
        } else if (msg.type === 'agent_done') {
          setAgentStatuses(prev => ({
            ...prev,
            [msg.agent]: { status: 'done', issueCount: msg.issue_count },
          }))
        } else if (msg.type === 'synthesis_token') {
          setStreamText(prev => prev + msg.content)
        } else if (msg.type === 'token') {
          // v0.1.0 兼容：单节点模式下的 token
          setStreamText(prev => prev + msg.content)
        } else if (msg.type === 'done') {
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

  return { phase, reviewId, streamText, review, errorMsg, agentStatuses, startReview }
}
