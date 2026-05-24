import { useState } from 'react'
import { useReview } from './hooks/useReview'
import type { AgentName } from './lib/types'
import { StreamOutput } from './components/StreamOutput'
import { IssueList } from './components/IssueList'
import { StatusBadge } from './components/StatusBadge'

const LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'go', 'rust', 'cpp', 'c']

const PLACEHOLDER = `# 粘贴你的代码片段，点击"开始审查"
def transfer(sender_id, receiver_id, amount):
    sender = db.query(f"SELECT * FROM users WHERE id={sender_id}")
    receiver = db.query(f"SELECT * FROM users WHERE id={receiver_id}")
    sender.balance -= amount
    receiver.balance += amount
    db.execute(f"UPDATE users SET balance={sender.balance} WHERE id={sender_id}")
    db.execute(f"UPDATE users SET balance={receiver.balance} WHERE id={receiver_id}")
`

const AGENT_LABELS: Record<AgentName, string> = {
  security:    '🔒 Security',
  performance: '⚡ Performance',
  style:       '✏️ Style',
  synthesis:   '📝 Synthesis',
}

const AGENT_ORDER: AgentName[] = ['security', 'performance', 'style', 'synthesis']

export default function App() {
  const [code, setCode] = useState('')
  const [language, setLanguage] = useState('python')
  const { phase, streamText, review, errorMsg, agentStatuses, startReview } = useReview()

  const isRunning = phase === 'submitting' || phase === 'streaming'
  const isDone = phase === 'done'
  const isError = phase === 'error'
  const showAgents = phase !== 'idle'

  const handleSubmit = () => {
    if (!code.trim() || isRunning) return
    startReview(code, language)
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-800 px-6 py-3 flex items-center gap-3 shrink-0">
        <span className="text-lg font-bold tracking-tight text-white">CodeSentinel</span>
        <span className="text-xs text-slate-500 font-mono">AI Code Review</span>
        <div className="ml-auto">
          {phase !== 'idle' && (
            <StatusBadge status={
              isRunning ? 'running'
              : isDone   ? 'done'
              : isError  ? 'failed'
              : 'pending'
            } />
          )}
        </div>
      </header>

      {/* Main two-column layout */}
      <main className="flex flex-1 overflow-hidden">
        {/* Left panel — code input */}
        <div className="w-1/2 flex flex-col border-r border-slate-800 p-4 gap-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-400 font-medium">语言</label>
            <select
              value={language}
              onChange={e => setLanguage(e.target.value)}
              className="bg-slate-800 text-slate-200 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none focus:border-slate-500"
            >
              {LANGUAGES.map(l => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
            <button
              onClick={handleSubmit}
              disabled={isRunning || !code.trim()}
              className="ml-auto px-4 py-1.5 rounded text-sm font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {isRunning ? '审查中…' : '开始审查'}
            </button>
          </div>

          <textarea
            value={code}
            onChange={e => setCode(e.target.value)}
            placeholder={PLACEHOLDER}
            spellCheck={false}
            className="flex-1 bg-slate-900 text-slate-200 font-mono text-sm rounded-lg p-4 border border-slate-700 focus:outline-none focus:border-slate-500 resize-none leading-relaxed placeholder:text-slate-600"
          />

          {/* Agent 进度面板 */}
          {showAgents && (
            <div className="flex gap-2 pt-1">
              {AGENT_ORDER.map(agent => {
                const s = agentStatuses[agent]
                return (
                  <div
                    key={agent}
                    className={`flex-1 rounded px-2 py-1.5 text-xs text-center transition-colors ${
                      s.status === 'done'    ? 'bg-green-900 text-green-300' :
                      s.status === 'running' ? 'bg-blue-900 text-blue-300 animate-pulse' :
                                              'bg-slate-800 text-slate-500'
                    }`}
                  >
                    <div>{AGENT_LABELS[agent]}</div>
                    {s.status === 'done' && s.issueCount !== undefined && agent !== 'synthesis' && (
                      <div className="text-xs opacity-70">{s.issueCount} issues</div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Right panel — output */}
        <div className="w-1/2 flex flex-col p-4 gap-3 overflow-hidden">
          {isError && (
            <div className="rounded-lg bg-red-950 border border-red-800 text-red-300 text-sm px-4 py-3">
              {errorMsg}
            </div>
          )}

          {isDone && review ? (
            <IssueList issues={review.issues} durationMs={review.duration_ms} />
          ) : (
            <StreamOutput text={streamText} done={isDone} />
          )}
        </div>
      </main>
    </div>
  )
}
