import { NavLink, Outlet } from 'react-router-dom'

const NAV = [
  { to: '/',             label: '🔍 New Review' },
  { to: '/dashboard',    label: '📋 History'    },
  { to: '/repositories', label: '🗂 Repos'       },
  { to: '/metrics',      label: '📊 Metrics'    },
]

export function Layout() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top bar */}
      <header className="border-b border-slate-800 px-6 py-3 flex items-center gap-4 shrink-0">
        <span className="text-lg font-bold tracking-tight text-white">CodeSentinel</span>
        <span className="text-xs text-slate-500 font-mono">AI Code Review</span>

        <nav className="ml-8 flex gap-1">
          {NAV.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded text-sm transition-colors ${
                  isActive
                    ? 'bg-indigo-700 text-white'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </header>

      {/* Page content */}
      <main className="flex flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}
