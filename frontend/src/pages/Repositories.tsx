import { useEffect, useState } from 'react'
import { repositoryApi, type Repository } from '../lib/api'

const PLATFORMS = ['github', 'gitlab', 'gitee'] as const
type Platform = typeof PLATFORMS[number]

export function Repositories() {
  const [platform, setPlatform] = useState<Platform>('github')
  const [url, setUrl]           = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError]   = useState<string | null>(null)

  const [repos, setRepos]       = useState<Repository[]>([])
  const [loading, setLoading]   = useState(true)
  const [indexing, setIndexing] = useState<Record<string, boolean>>({})

  useEffect(() => {
    repositoryApi.list()
      .then(r => setRepos(r.data))
      .catch(() => {/* silently ignore, show empty list */})
      .finally(() => setLoading(false))
  }, [])

  async function handleCreate() {
    if (!url.trim()) return
    setSubmitting(true)
    setFormError(null)
    try {
      const res = await repositoryApi.create({ platform, url: url.trim() })
      setRepos(prev => [res.data, ...prev])
      setUrl('')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setFormError(msg ?? '注册失败，请检查 URL 格式')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('确认删除该仓库？所有 CodeChunk 也会一并清除。')) return
    try {
      await repositoryApi.delete(id)
      setRepos(prev => prev.filter(r => r.id !== id))
    } catch {
      alert('删除失败')
    }
  }

  async function handleIndex(id: string) {
    setIndexing(prev => ({ ...prev, [id]: true }))
    try {
      await repositoryApi.triggerIndex(id)
      // Optimistic: mark indexed_at as pending; real value comes after task finishes
    } catch {
      alert('触发索引失败')
    } finally {
      setIndexing(prev => ({ ...prev, [id]: false }))
    }
  }

  return (
    <div className="flex-1 flex flex-col p-6 gap-6 overflow-auto">
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
              {p}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">仓库 URL</label>
          <input
            type="url"
            value={url}
            onChange={e => { setUrl(e.target.value); setFormError(null) }}
            placeholder="https://github.com/owner/repo"
            className="bg-slate-800 text-slate-200 text-sm rounded px-3 py-2 border border-slate-700 focus:outline-none focus:border-slate-500"
          />
        </div>

        {formError && (
          <p className="text-red-400 text-xs">{formError}</p>
        )}

        <button
          disabled={!url.trim() || submitting}
          className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium transition-colors"
          onClick={handleCreate}
        >
          {submitting ? '注册中…' : '注册仓库'}
        </button>
      </div>

      {/* Repo list */}
      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-slate-300">已注册仓库</h2>
        {loading ? (
          <p className="text-slate-500 text-sm">加载中…</p>
        ) : repos.length === 0 ? (
          <p className="text-slate-500 text-sm">暂无已注册仓库</p>
        ) : (
          repos.map(repo => (
            <div
              key={repo.id}
              className="bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 flex items-center gap-4"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{repo.url}</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  {repo.indexed_at
                    ? `已索引 · ${new Date(repo.indexed_at).toLocaleString('zh-CN')}`
                    : '未索引'}
                </p>
              </div>
              <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 shrink-0">
                {repo.platform}
              </span>
              <button
                disabled={indexing[repo.id]}
                onClick={() => handleIndex(repo.id)}
                className="text-xs px-3 py-1.5 rounded bg-emerald-800 hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed text-emerald-200 transition-colors shrink-0"
              >
                {indexing[repo.id] ? '入队中…' : '触发索引'}
              </button>
              <button
                onClick={() => handleDelete(repo.id)}
                className="text-xs px-3 py-1.5 rounded bg-red-900 hover:bg-red-800 text-red-300 transition-colors shrink-0"
              >
                删除
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
