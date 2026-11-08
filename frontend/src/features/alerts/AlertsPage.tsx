import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { api, qs } from '../../api/client'
import type { AlertPage } from '../../api/types'
import { formatIst, ms, relativeTime } from '../../components/format'
import { Button, Card, Empty, inputClass, PageHeader } from '../../components/ui'
import { useMe } from '../auth/useAuth'

interface AlertTime {
  alert_id: string
  nc_id: string
  nc_no: string
  kind: string
  title: string
  source_received_at: string | null
  created_at: string
  generation_ms: number | null
  email_ms: number | null
}

const KIND_STYLE: Record<string, string> = {
  NOK: 'bg-red-100 text-red-800',
  RECURRENCE: 'bg-orange-100 text-orange-800',
  ESCALATION: 'bg-violet-100 text-violet-800',
  SPC_WARNING: 'bg-amber-100 text-amber-900',
  SYSTEM: 'bg-slate-100 text-slate-700',
}

export function AlertsPage() {
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const view = params.get('view') ?? 'mine'
  const [kind, setKind] = useState('')
  const queryClient = useQueryClient()
  const plantWide = me.data && ['QUALITY_HEAD', 'ADMIN', 'VIEWER'].includes(me.data.role)
  const alerts = useQuery({
    queryKey: ['alerts', view, kind],
    queryFn: () => api.get<AlertPage>(`/alerts${qs({ mine: view !== 'all', kind, limit: 100 })}`),
    enabled: view !== 'times',
  })
  const times = useQuery({ queryKey: ['kpi', 'alert-times'], queryFn: () => api.get<AlertTime[]>('/kpi/alert-times'), enabled: view === 'times' })
  const read = useMutation({
    mutationFn: (id: string) => api.post(`/alerts/${id}/read`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  })

  const tab = (key: string, label: string) => (
    <button
      type="button"
      onClick={() => setParams({ view: key })}
      className={`min-h-10 rounded-md px-3 py-2 text-sm ${view === key ? 'bg-slate-900 text-white' : 'bg-white text-slate-700 hover:bg-slate-100'}`}
    >
      {label}
    </button>
  )

  return (
    <div className="space-y-4">
      <PageHeader title="Alerts" subtitle="Not OK results go to the named owner within seconds; unacknowledged ones escalate." />
      <div className="flex flex-wrap gap-2">
        {tab('mine', 'My alerts')}
        {plantWide && tab('all', 'All alerts')}
        {tab('times', 'Alert generation times (K3)')}
        {view !== 'times' && (
          <select className={`${inputClass} w-48`} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">
            <option value="">All kinds</option>
            {Object.keys(KIND_STYLE).map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        )}
      </div>
      {view === 'times' ? (
        <Card title={`Every Not OK alert with its generation time (${times.data?.length ?? 0})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500 uppercase">
                <tr>
                  <th className="py-2">NC</th>
                  <th>Kind</th>
                  <th>File received (IST)</th>
                  <th>Alert created</th>
                  <th className="text-right">Generation</th>
                  <th className="text-right">Email</th>
                </tr>
              </thead>
              <tbody>
                {times.data?.map((t) => (
                  <tr key={t.alert_id} className="border-t border-slate-100">
                    <td className="py-1.5">
                      <Link className="underline" to={`/ncs/${t.nc_id}`}>
                        {t.nc_no}
                      </Link>
                    </td>
                    <td>{t.kind}</td>
                    <td>{formatIst(t.source_received_at, true)}</td>
                    <td>{formatIst(t.created_at, true)}</td>
                    <td className="text-right font-medium tabular-nums">{ms(t.generation_ms)}</td>
                    <td className="text-right tabular-nums">{ms(t.email_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <Card title={`${alerts.data?.total ?? 0} alerts · ${alerts.data?.unread ?? 0} unread`}>
          {alerts.data?.items.length === 0 && <Empty>No alerts.</Empty>}
          <ul className="divide-y divide-slate-100">
            {alerts.data?.items.map((a) => (
              <li key={a.id} className={`flex flex-wrap items-start gap-3 py-3 ${a.read_at ? '' : 'bg-red-50/40'}`}>
                <span className={`rounded px-2 py-0.5 text-xs font-semibold ${KIND_STYLE[a.kind]}`}>{a.kind.replace('_', ' ')}</span>
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{a.title}</div>
                  <pre className="mt-1 font-sans text-xs whitespace-pre-wrap text-slate-600">{a.body}</pre>
                  <div className="mt-1 text-xs text-slate-500">
                    {relativeTime(a.created_at)} · {formatIst(a.created_at, true)} · to {a.recipient_name ?? '-'}
                    {a.generation_ms !== null && ` · generated in ${ms(a.generation_ms)}`}
                    {a.acknowledged_at && ' · acknowledged'}
                  </div>
                </div>
                <div className="flex gap-2">
                  {a.nc_id && (
                    <Link to={`/ncs/${a.nc_id}`} className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50">
                      Open {a.nc_no}
                    </Link>
                  )}
                  {!a.read_at && view === 'mine' && (
                    <Button variant="ghost" onClick={() => read.mutate(a.id)}>
                      Mark read
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
