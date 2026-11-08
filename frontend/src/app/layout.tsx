import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect } from 'react'
import { Navigate, NavLink, Outlet, useNavigate } from 'react-router'

import { api, ApiError } from '../api/client'
import { useLiveEvents, type LiveEvent } from '../api/sse'
import { cn } from '../components/cn'
import { DemoDataBadge } from '../components/DemoDataBadge'
import { ROLE_LABEL } from '../components/format'
import { AlertBell } from '../features/alerts/AlertBell'
import { can, useMe } from '../features/auth/useAuth'
import { useToast } from './toastContext'

function beep() {
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    osc.frequency.value = 880
    osc.connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.15)
  } catch {
    /* sound is optional */
  }
}

export function Layout() {
  const me = useMe()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const user = me.data
  const role = user?.role

  const onAlert = useCallback(
    (event: LiveEvent) => {
      toast.push({
        tone: event.kind === 'SPC_WARNING' ? 'info' : 'alert',
        title: event.title ?? 'New alert',
        body: event.kind === 'ESCALATION' ? 'Escalated to you: not acknowledged in time' : undefined,
        to: event.nc_id ? `/ncs/${event.nc_id}` : '/alerts',
      })
      if (localStorage.getItem('alertSound') !== 'off' && event.kind !== 'SPC_WARNING') beep()
    },
    [toast],
  )
  const live = useLiveEvents(Boolean(user), onAlert)

  const logout = useMutation({
    mutationFn: () => api.post('/auth/logout'),
    onSettled: () => {
      queryClient.clear()
      void navigate('/login')
    },
  })

  useEffect(() => {
    document.title = 'Smart CMM Quality'
  }, [])

  if (me.isPending) return <div className="p-8 text-slate-500">Loading…</div>
  if (me.error instanceof ApiError && me.error.status === 401) return <Navigate to="/login" replace />
  if (!user) return <div className="p-8 text-red-700">Cannot reach the API. Is `make up` running?</div>

  const nav: { to: string; label: string; show: boolean }[] = [
    { to: '/', label: 'Dashboard', show: true },
    { to: '/reports', label: 'Reports', show: true },
    { to: '/ncs', label: 'Non-conformances', show: true },
    { to: '/alerts', label: 'Alerts', show: true },
    { to: '/spc', label: 'SPC', show: true },
    { to: '/mapping', label: 'Mapping', show: can.upload(role) || can.masters(role) },
    { to: '/audit', label: 'Audit log', show: can.audit(role) },
    { to: '/settings', label: 'Settings', show: can.settings(role) },
    { to: '/masters', label: 'Masters', show: true },
  ]

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-[1400px] items-center gap-4 px-4 py-2">
          <NavLink to="/" className="text-lg font-semibold whitespace-nowrap">
            Smart CMM Quality
          </NavLink>
          <nav className="flex flex-1 gap-1 overflow-x-auto" aria-label="Main">
            {nav
              .filter((n) => n.show)
              .map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.to === '/'}
                  className={({ isActive }) =>
                    cn('rounded-md px-3 py-2 text-sm whitespace-nowrap', isActive ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-100')
                  }
                >
                  {n.label}
                </NavLink>
              ))}
          </nav>
          <span
            className={cn('h-2.5 w-2.5 rounded-full', live ? 'bg-green-500' : 'bg-slate-300')}
            title={live ? 'Live updates connected' : 'Live updates disconnected'}
            aria-label={live ? 'live' : 'offline'}
          />
          <DemoDataBadge />
          <AlertBell />
          <div className="text-right text-xs leading-tight">
            <div className="font-medium">{user.full_name}</div>
            <div className="text-slate-500">{ROLE_LABEL[user.role]}</div>
          </div>
          <button type="button" className="rounded-md px-2 py-2 text-xs text-slate-600 hover:bg-slate-100" onClick={() => logout.mutate()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6">
        <Outlet />
      </main>
      <footer className="border-t border-slate-200 py-3 text-center text-xs text-slate-500">
        Prototype for Sakthi Hackathon 2.0 · all data shown is synthetic demo data · times in IST
      </footer>
    </div>
  )
}
