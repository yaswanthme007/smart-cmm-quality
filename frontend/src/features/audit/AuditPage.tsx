import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'

import { api, qs } from '../../api/client'
import type { AuditEntry, Page } from '../../api/types'
import { formatIst } from '../../components/format'
import { Card, Empty, inputClass, PageHeader } from '../../components/ui'

function Json({ value }: { value: Record<string, unknown> | null }) {
  if (!value) return <span className="text-slate-400">-</span>
  return <pre className="max-w-md overflow-x-auto font-mono text-[11px] whitespace-pre-wrap text-slate-700">{JSON.stringify(value, null, 1)}</pre>
}

export function AuditPage() {
  const [params, setParams] = useSearchParams()
  const filters = Object.fromEntries(params.entries())
  const entries = useQuery({ queryKey: ['audit', filters], queryFn: () => api.get<Page<AuditEntry>>(`/audit${qs({ ...filters, limit: 200 })}`) })
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
  }
  return (
    <div className="space-y-4">
      <PageHeader title="Audit log" subtitle="Append-only: the database rejects any UPDATE or DELETE on this table. Every state change, who, when, before and after." />
      <div className="flex flex-wrap gap-2">
        <select className={`${inputClass} w-48`} value={params.get('entity') ?? ''} onChange={(e) => set('entity', e.target.value)} aria-label="Entity">
          <option value="">All entities</option>
          {['nonconformance', 'inspection_report', 'settings', 'spc_limits', 'spc_signal', 'mapping_profile', 'part', 'characteristic', 'user', 'machine'].map((e) => (
            <option key={e}>{e}</option>
          ))}
        </select>
        <input className={`${inputClass} w-56`} placeholder="Action contains…" value={params.get('action') ?? ''} onChange={(e) => set('action', e.target.value)} />
        <input className={`${inputClass} w-80`} placeholder="Entity id" value={params.get('entity_id') ?? ''} onChange={(e) => set('entity_id', e.target.value)} />
      </div>
      <Card title={`${entries.data?.total ?? 0} entries`}>
        {entries.data?.items.length === 0 ? (
          <Empty>No entries.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500 uppercase">
                <tr>
                  <th className="py-2">#</th>
                  <th>When (IST)</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Before</th>
                  <th>After</th>
                  <th>Request</th>
                </tr>
              </thead>
              <tbody>
                {entries.data?.items.map((a) => (
                  <tr key={a.id} className="border-t border-slate-100 align-top">
                    <td className="py-2 text-xs text-slate-500">{a.id}</td>
                    <td className="whitespace-nowrap">{formatIst(a.at, true)}</td>
                    <td>
                      {a.actor_name ?? 'System'}
                      <div className="text-xs text-slate-500">{a.actor_role}</div>
                    </td>
                    <td className="font-medium">{a.action}</td>
                    <td>
                      <button type="button" className="text-left text-xs underline" onClick={() => setParams({ entity: a.entity, entity_id: a.entity_id ?? '' })}>
                        {a.entity}
                        <div className="max-w-40 truncate text-slate-500">{a.entity_id}</div>
                      </button>
                    </td>
                    <td>
                      <Json value={a.before} />
                    </td>
                    <td>
                      <Json value={a.after} />
                    </td>
                    <td className="max-w-24 truncate text-xs text-slate-400" title={a.request_id ?? ''}>
                      {a.request_id}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
