import { useEffect, useRef } from 'react'

interface StreamOutputProps {
  text: string
  done: boolean
}

export function StreamOutput({ text, done }: StreamOutputProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // 自动滚动到最新内容
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [text])

  return (
    <div className="relative h-full">
      <pre className="font-mono text-sm text-green-300 bg-slate-950 rounded-lg p-4 h-full overflow-y-auto whitespace-pre-wrap leading-relaxed">
        {text || (
          <span className="text-slate-500 italic">审查结果将在此实时显示...</span>
        )}
        {!done && text && (
          <span className="inline-block w-2 h-4 bg-green-400 ml-0.5 animate-pulse align-text-bottom" />
        )}
        <div ref={bottomRef} />
      </pre>
    </div>
  )
}
