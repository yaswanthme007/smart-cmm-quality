import { useMachines, useParts, useProcesses } from '../api/masters'
import type { Filters } from '../api/types'
import { inputClass } from './ui'

export function FiltersBar({ filters, onChange }: { filters: Filters; onChange: (patch: Partial<Filters>) => void }) {
  const parts = useParts()
  const machines = useMachines()
  const processes = useProcesses()
  const select = (key: keyof Filters, label: string, options: { id: string; label: string }[] | undefined) => (
    <label className="flex flex-col text-xs text-slate-600">
      {label}
      <select className={`${inputClass} mt-1 min-w-36`} value={filters[key] ?? ''} onChange={(e) => onChange({ [key]: e.target.value })}>
        <option value="">All</option>
        {options?.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-3" role="search">
      <label className="flex flex-col text-xs text-slate-600">
        From
        <input type="date" className={`${inputClass} mt-1`} value={filters.date_from ?? ''} onChange={(e) => onChange({ date_from: e.target.value })} />
      </label>
      <label className="flex flex-col text-xs text-slate-600">
        To
        <input type="date" className={`${inputClass} mt-1`} value={filters.date_to ?? ''} onChange={(e) => onChange({ date_to: e.target.value })} />
      </label>
      {select('part_id', 'Part', parts.data)}
      {select('machine_id', 'Machine', machines.data)}
      {select('process_id', 'Process', processes.data)}
      {select('shift', 'Shift', [
        { id: 'A', label: 'A (06-14)' },
        { id: 'B', label: 'B (14-22)' },
        { id: 'C', label: 'C (22-06)' },
      ])}
      <button
        type="button"
        className="min-h-10 rounded-md px-3 text-sm text-slate-600 underline"
        onClick={() => onChange({ date_from: '', date_to: '', part_id: '', machine_id: '', process_id: '', shift: '' })}
      >
        Clear
      </button>
    </div>
  )
}
