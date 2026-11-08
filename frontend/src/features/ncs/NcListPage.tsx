import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'

import { api, qs } from '../../api/client'
import type { Nc, Page } from '../../api/types'
import { formatDate, formatIst, hours } from '../../components/format'
import { Card, Empty, inputClass, PageHeader, SeverityChip, StatusChip } from '../../components/ui'

const BUCKETS = [
  ['', 'All'],
  ['open', 'Open'],
  ['pending', 'Pending'],
  ['overdue', 'Overdue'],
  ['closed', 'Closed'],
  ['cancelled', 'Cancelled'],
] as const

export function NcListPage() {
  const [params, setParams] = useSearchParams()
  const filters = Object.fromEntries(params.entries())
  const ncs = useQuery({ queryKey: ['ncs', filters], queryFn: () => api.get<Page<Nc>>(`/ncs${qs({ ...filters, limit: 200 })}`) })
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Non-conformances"
        subtitle="One NC per Not OK part: owner, status, age and corrective action."
        actions={
          <a className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50" href="/api/exports/ncs.xlsx">
            Export Excel
          </a>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        {BUCKETS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => set('bucket', key)}
            className={`min-h-10 rounded-md px-3 py-2 text-sm ${(params.get('bucket') ?? '') === key ? 'bg-slate-900 text-white' : 'bg-white text-slate-700 hover:bg-slate-100'}`}
          >
            {label}
          </button>
        ))}
        <select className={`${inputClass} w-40`} value={params.get('severity') ?? ''} onChange={(e) => set('severity', e.target.value)} aria-label="Severity">
          <option value="">Any severity</option>
          <option>CRITICAL</option>
          <option>SIGNIFICANT</option>
          <option>STANDARD</option>
        </select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={params.get('mine') === 'true'} onChange={(e) => set('mine', e.target.checked ? 'true' : '')} />
          Mine only
        </label>
        <input className={`${inputClass} w-44`} placeholder="Search NC no." value={params.get('q') ?? ''} onChange={(e) => set('q', e.target.value)} />
      </div>
      <Card title={`${ncs.data?.total ?? 0} non-conformances`}>
        {ncs.data?.items.length === 0 ? (
          <Empty>Nothing here.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500 uppercase">
                <tr>
                  <th className="py-2">NC</th>
                  <th>Status</th>
                  <th>Severity</th>
                  <th>Part</th>
                  <th>Machine</th>
                  <th>Characteristics</th>
                  <th>Owner</th>
                  <th>Detected (IST)</th>
                  <th>Age</th>
                  <th>Target</th>
                </tr>
              </thead>
              <tbody>
                {ncs.data?.items.map((n) => (
                  <tr key={n.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="py-2">
                      <Link className="font-semibold hover:underline" to={`/ncs/${n.id}`}>
                        {n.nc_no}
                      </Link>
                      {n.escalation_level > 0 && <span className="ml-2 rounded bg-violet-100 px-1 text-[10px] font-semibold text-violet-800">ESC L{n.escalation_level}</span>}
                      {n.recurrence_count > 0 && <span className="ml-1 rounded bg-orange-100 px-1 text-[10px] font-semibold text-orange-800">×{n.recurrence_count + 1}</span>}
                    </td>
                    <td>
                      <StatusChip status={n.status} />
                      {n.overdue && <span className="ml-1 text-xs font-semibold text-amber-800">Overdue</span>}
                    </td>
                    <td>
                      <SeverityChip severity={n.severity} />
                    </td>
                    <td>{n.part_no}</td>
                    <td>{n.machine_code}</td>
                    <td>{n.characteristics.join(', ')}</td>
                    <td>{n.owner_name}</td>
                    <td>{formatIst(n.detected_at)}</td>
                    <td>{hours(n.age_hours)}</td>
                    <td>{formatDate(n.target_date)}</td>
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
