import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/client'
import type { MasterRow } from '../../api/types'
import { num, ROLE_LABEL } from '../../components/format'
import { Button, Card, ErrorBox, inputClass, PageHeader, SeverityChip } from '../../components/ui'
import type { Severity } from '../../api/types'
import { can, useMe } from '../auth/useAuth'

type Tab = 'parts' | 'machines' | 'processes' | 'owners' | 'users'

function useRows(path: string, enabled = true) {
  return useQuery({ queryKey: ['masters', path], queryFn: () => api.get<MasterRow[]>(path), enabled })
}

function CharacteristicsTable({ partId, admin }: { partId: string; admin: boolean }) {
  const chars = useRows(`/parts/${partId}/characteristics`)
  const queryClient = useQueryClient()
  const [edit, setEdit] = useState<MasterRow | null>(null)
  const save = useMutation({
    mutationFn: (row: MasterRow) => {
      const body = {
        char_no: row.char_no,
        name: row.name,
        kind: row.kind,
        tolerance_type: row.tolerance_type,
        nominal: row.nominal === null ? null : Number(row.nominal),
        usl: row.usl === null || row.usl === '' ? null : Number(row.usl),
        lsl: row.lsl === null || row.lsl === '' ? null : Number(row.lsl),
        reference_width: row.reference_width === null ? null : Number(row.reference_width),
        unit: row.unit,
        decimals: Number(row.decimals),
        classification: row.classification,
        process_id: row.process_id,
        guard_band_pct: row.guard_band_pct === null || row.guard_band_pct === '' ? null : Number(row.guard_band_pct),
        expanded_uncertainty: row.expanded_uncertainty === null || row.expanded_uncertainty === '' ? null : Number(row.expanded_uncertainty),
        is_active: row.is_active,
      }
      return api.put(`/characteristics/${row.id}`, body)
    },
    onSuccess: () => {
      setEdit(null)
      void queryClient.invalidateQueries({ queryKey: ['masters'] })
    },
  })
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500 uppercase">
          <tr>
            <th className="py-1">Char</th>
            <th>Name</th>
            <th>Type</th>
            <th>Class</th>
            <th className="text-right">Nominal</th>
            <th className="text-right">LSL</th>
            <th className="text-right">USL</th>
            <th className="text-right">Guard band %</th>
            <th className="text-right">U</th>
            {admin && <th />}
          </tr>
        </thead>
        <tbody>
          {chars.data?.map((c) =>
            edit?.id === c.id ? (
              <tr key={c.id} className="border-t border-slate-100 bg-amber-50">
                <td className="py-1">{String(c.char_no)}</td>
                <td>{String(c.name)}</td>
                <td className="text-xs">{String(c.tolerance_type)}</td>
                <td>
                  <select className={inputClass} value={String(edit.classification)} onChange={(e) => setEdit({ ...edit, classification: e.target.value })}>
                    <option>CRITICAL</option>
                    <option>SIGNIFICANT</option>
                    <option>STANDARD</option>
                  </select>
                </td>
                <td className="text-right">{num(c.nominal as string)}</td>
                {(['lsl', 'usl', 'guard_band_pct', 'expanded_uncertainty'] as const).map((k) => (
                  <td key={k}>
                    <input className={`${inputClass} w-24 text-right`} value={(edit[k] as string) ?? ''} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />
                  </td>
                ))}
                <td className="whitespace-nowrap">
                  <Button onClick={() => save.mutate(edit)}>Save</Button>
                  <Button variant="ghost" onClick={() => setEdit(null)}>
                    Cancel
                  </Button>
                </td>
              </tr>
            ) : (
              <tr key={c.id} className="border-t border-slate-100">
                <td className="py-1 font-medium">{String(c.char_no)}</td>
                <td>{String(c.name)}</td>
                <td className="text-xs">{String(c.tolerance_type)}</td>
                <td>
                  <SeverityChip severity={c.classification as Severity} />
                </td>
                <td className="text-right tabular-nums">{num(c.nominal as string)}</td>
                <td className="text-right tabular-nums">{num(c.lsl as string)}</td>
                <td className="text-right tabular-nums">{num(c.usl as string)}</td>
                <td className="text-right">{c.guard_band_pct === null ? 'default' : String(c.guard_band_pct)}</td>
                <td className="text-right">{c.expanded_uncertainty === null ? '-' : num(c.expanded_uncertainty as string)}</td>
                {admin && (
                  <td>
                    <Button variant="ghost" onClick={() => setEdit(c)}>
                      Edit
                    </Button>
                  </td>
                )}
              </tr>
            ),
          )}
        </tbody>
      </table>
      <ErrorBox error={save.error} />
    </div>
  )
}

function SimpleTable({ rows, columns }: { rows: MasterRow[] | undefined; columns: [string, string, ((r: MasterRow) => string)?][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500 uppercase">
          <tr>
            {columns.map(([, label]) => (
              <th key={label} className="py-2">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows?.map((r) => (
            <tr key={r.id} className="border-t border-slate-100">
              {columns.map(([key, label, render]) => (
                <td key={label} className="py-1.5">
                  {render ? render(r) : String(r[key] ?? '-')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function MastersPage() {
  const me = useMe()
  const admin = can.masters(me.data?.role)
  const [tab, setTab] = useState<Tab>('parts')
  const parts = useRows('/parts')
  const machines = useRows('/machines')
  const processes = useRows('/processes')
  const people = useRows('/people')
  const rules = useRows('/ownership-rules')
  const users = useRows('/users', admin)
  const name = (rows: MasterRow[] | undefined, id: unknown, key: string) => String(rows?.find((r) => r.id === id)?.[key] ?? '-')

  const tabs: [Tab, string][] = [
    ['parts', 'Parts & characteristics'],
    ['machines', 'Machines'],
    ['processes', 'Processes'],
    ['owners', 'Ownership rules'],
    ...(admin ? ([['users', 'Users']] as [Tab, string][]) : []),
  ]

  return (
    <div className="space-y-4">
      <PageHeader title="Master data" subtitle="Drawing limits live here (source of truth), not in the CMM report. All values are synthetic demo data." />
      <div className="flex flex-wrap gap-2">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`min-h-10 rounded-md px-3 py-2 text-sm ${tab === key ? 'bg-slate-900 text-white' : 'bg-white text-slate-700 hover:bg-slate-100'}`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'parts' &&
        parts.data?.map((p) => (
          <Card key={p.id} title={`${String(p.part_no)} ${String(p.name)} · drawing ${String(p.drawing_no)} rev ${String(p.drawing_rev)}`}>
            <CharacteristicsTable partId={p.id} admin={admin} />
          </Card>
        ))}
      {tab === 'machines' && (
        <Card title="Machines">
          <SimpleTable
            rows={machines.data}
            columns={[
              ['code', 'Code'],
              ['name', 'Name'],
              ['process_id', 'Process', (r) => name(processes.data, r.process_id, 'code')],
              ['line', 'Line'],
              ['is_active', 'Active', (r) => (r.is_active ? 'yes' : 'no')],
            ]}
          />
        </Card>
      )}
      {tab === 'processes' && (
        <Card title="Processes">
          <SimpleTable
            rows={processes.data}
            columns={[
              ['code', 'Code'],
              ['name', 'Name'],
            ]}
          />
        </Card>
      )}
      {tab === 'owners' && (
        <Card title="Ownership rules (most specific wins: machine > process > part > department head)">
          <SimpleTable
            rows={rules.data}
            columns={[
              ['machine_id', 'Machine', (r) => (r.machine_id ? name(machines.data, r.machine_id, 'code') : '-')],
              ['process_id', 'Process', (r) => (r.process_id ? name(processes.data, r.process_id, 'code') : '-')],
              ['owner_user_id', 'Owner', (r) => name(people.data, r.owner_user_id, 'full_name')],
              ['supervisor_user_id', 'Supervisor', (r) => name(people.data, r.supervisor_user_id, 'full_name')],
              ['priority', 'Priority'],
            ]}
          />
        </Card>
      )}
      {tab === 'users' && admin && (
        <Card title="Users">
          <SimpleTable
            rows={users.data}
            columns={[
              ['full_name', 'Name'],
              ['email', 'Email'],
              ['role', 'Role', (r) => ROLE_LABEL[String(r.role)] ?? String(r.role)],
              ['is_active', 'Active', (r) => (r.is_active ? 'yes' : 'no')],
            ]}
          />
        </Card>
      )}
    </div>
  )
}
