import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/client'
import type { ReportDetail } from '../../api/types'
import { Button, Card, ErrorBox, Field, inputClass } from '../../components/ui'

interface Proposal {
  part_no: string | null
  serial_no: string | null
  machine_code: string | null
  rows: { char_no: string; char_name: string | null; actual: string; nominal: string | null; usl: string | null; lsl: string | null }[]
}

/** Human confirmation of AI-extracted PDF rows (Section 19). Nothing is classified before this. */
export function ConfirmRows({ report }: { report: ReportDetail }) {
  const pending = report.warnings.find((w) => w.code === 'PENDING_ROWS') as unknown as { data: Proposal } | undefined
  const [header, setHeader] = useState({
    part_no: pending?.data.part_no ?? '',
    serial_no: pending?.data.serial_no ?? '',
    machine_code: pending?.data.machine_code ?? '',
  })
  const [rows, setRows] = useState(pending?.data.rows.map((r) => ({ ...r, keep: true })) ?? [])
  const queryClient = useQueryClient()
  const confirm = useMutation({
    mutationFn: () =>
      api.post(`/reports/${report.id}/confirm`, {
        ...header,
        rows: rows
          .filter((r) => r.keep)
          .map((r) => ({ char_no: r.char_no, actual: r.actual, char_name: r.char_name, nominal: r.nominal || null, usl: r.usl || null, lsl: r.lsl || null })),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reports'] }),
  })
  if (!pending) return null
  return (
    <Card title="AI-extracted rows: check each against the PDF, then confirm">
      <p className="mb-3 text-xs text-slate-600">Suggested by the optional AI module. Only confirmed rows are classified; limits come from master data.</p>
      <div className="mb-3 grid gap-3 md:grid-cols-3">
        {(['part_no', 'serial_no', 'machine_code'] as const).map((k) => (
          <Field key={k} label={k}>
            <input className={inputClass} value={header[k]} onChange={(e) => setHeader({ ...header, [k]: e.target.value })} />
          </Field>
        ))}
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500 uppercase">
          <tr>
            <th>Use</th>
            <th>Char</th>
            <th>Name</th>
            <th>Actual</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-slate-100">
              <td>
                <input type="checkbox" checked={r.keep} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, keep: e.target.checked } : x)))} />
              </td>
              <td>
                <input className={inputClass} value={r.char_no} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, char_no: e.target.value } : x)))} />
              </td>
              <td className="text-slate-600">{r.char_name}</td>
              <td>
                <input className={inputClass} value={r.actual} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, actual: e.target.value } : x)))} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ErrorBox error={confirm.error} />
      <Button className="mt-3" onClick={() => confirm.mutate()} disabled={confirm.isPending}>
        Confirm and classify
      </Button>
    </Card>
  )
}
