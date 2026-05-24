import { useState } from 'react'

const PLATFORMS = ['github', 'gitlab', 'gitee'] as const
type Platform = typeof PLATFORMS[number]

const PLATFORM_ICONS: Record<Platform, string> = {
  github: '🐙',
  gitlab: '🦊',
  gitee:  '🟠',
}

export function Repositories() {
  const [platform, setPlatform] = useState<Platform>('github')
  const [url, setUrl]           = useState('')
  const [secret, setSecret]     = useState('')

  return (
    <div className="flex-1 flex flex-col p-6 gap-6 overflow-auto">
      {/* Coming soon banner */}
      <div className="rounded-lg bg-amber-950 border border-amber-700 px-4 py-3 text-amber-300 text-sm">
        仓库 Webhook 集成尚在开发中（后端 API v0.3 规划）。表单已就绪，提交后会显示 501 提示。
      </div>

      {/* Register form */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 max-w-lg flex flex-col gap-4">
        <h2 className="text-base font-semibold text-white">注册 Git 仓库</h2>

        <div className="flex gap-2">
          {PLATFORMS.map(p => (
            <button
              key={p}
              onClick={() => setPlatform(p)}
              className={`flex-1 py-2 rounded text-sm transition-colors ${
                platform === p
                  ? 'bg-indigo-700 text-white'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
            >
              {PLATFORM_ICONS[p]} {p}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">仓库 URL</label>
          <input
            type="url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            className="bg-slate-800 text-slate-200 text-sm rounded px-3 py-2 border border-slate-700 focus:outline-none focus:border-slate-500"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">Webhook Secret</label>
          <input
            type="password"
            value={secret}
            onChange={e => setSecret(e.target.value)}
            placeholder="your-webhook-secret"
            className="bg-slate-800 text-slate-200 text-sm rounded px-3 py-2 border border-slate-700 focus:outline-none focus:border-slate-500"
          />
        </div>

        <button
          disabled={!url.trim() || !secret.trim()}
          className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium transition-colors"
          onClick={() => alert('后端 API 尚未实现 (501)')}
        >
          注册仓库
        </button>
      </div>

      {/* Placeholder list */}
      <div className="text-slate-500 text-sm">已注册仓库将显示在此处…</div>
    </div>
  )
}
