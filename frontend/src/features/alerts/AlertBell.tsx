import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'

import { api } from '../../api/client'
import type { AlertPage } from '../../api/types'
import { ms, relativeTime } from '../../components/format'

export function AlertBell() {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const alerts = useQuery({ queryKey: ['alerts', 'bell'], queryFn: () => api.get<AlertPage>('/alerts?mine=true&limit=8') })
  const readAll = useMutation({
    mutationFn: () => api.post('/alerts/read-all'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  })
  const unread = alerts.data?.unread ?? 0

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="relative min-h-10 rounded-md px-3 py-2 hover:bg-slate-100"
        aria-label={`Alerts, ${unread} unread`}
      >
        <span aria-hidden className="text-lg">
          🔔
        </span>
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-5 rounded-full bg-red-600 px-1 text-center text-[11px] font-bold text-white">
            {unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-96 max-w-[90vw] rounded-lg border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
            <span className="text-sm font-semibold">My alerts</span>
            <button type="button" className="text-xs text-slate-600 underline" onClick={() => readAll.mutate()}>
              Mark all read
            </button>
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {alerts.data?.items.length === 0 && <li className="p-4 text-sm text-slate-500">No alerts.</li>}
            {alerts.data?.items.map((a) => (
              <li key={a.id} className={`border-b border-slate-100 px-3 py-2 text-sm ${a.read_at ? '' : 'bg-red-50/50'}`}>
                <Link to={a.nc_id ? `/ncs/${a.nc_id}` : '/alerts'} onClick={() => setOpen(false)} className="block">
                  <div className="font-medium">{a.title}</div>
                  <div className="mt-0.5 text-xs text-slate-500">
                    {relativeTime(a.created_at)}
                    {a.generation_ms !== null && ` · alert in ${ms(a.generation_ms)}`}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <Link to="/alerts" onClick={() => setOpen(false)} className="block px-3 py-2 text-center text-xs font-medium text-slate-700 hover:bg-slate-50">
            All alerts
          </Link>
        </div>
      )}
    </div>
  )
}
