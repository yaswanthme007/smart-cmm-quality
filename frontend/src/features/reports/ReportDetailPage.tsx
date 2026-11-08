import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'

import { api } from '../../api/client'
import type { ReportDetail } from '../../api/types'
import { formatIst, num } from '../../components/format'
import { Card, ErrorBox, LimitBar, PageHeader, ResultChip, SeverityChip } from '../../components/ui'
import { ConfirmRows } from './ConfirmRows'

export function ReportDetailPage() {
  const { id } = useParams()
  const report = useQuery({ queryKey: ['reports', id], queryFn: () => api.get<ReportDetail>(`/reports/${id}`) })
  const r = report.data
  if (report.error) return <ErrorBox error={report.error} />
  if (!r) return <div className="text-slate-500">Loading…</div>

  return (
    <div className="space-y-4">
      <PageHeader
        title={`Report ${r.report_no}`}
        subtitle={`${r.part_no ?? '?'} ${r.part_name ?? ''} · SN ${r.serial_no ?? '-'} · ${r.machine_code ?? '-'} / ${r.process_code ?? '-'}`}
        actions={
          <a className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50" href={`/api/exports/reports/${r.id}.pdf`}>
            PDF
          </a>
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Verdict">
          <div className="flex items-center gap-3">
            {r.status === 'FAILED' ? (
              <span className="font-semibold text-red-700">FAILED</span>
            ) : r.status === 'NEEDS_CONFIRMATION' ? (
              <span className="font-semibold text-amber-800">Needs confirmation</span>
            ) : (
              <ResultChip result={r.part_result} />
            )}
            <span className="text-sm text-slate-600">
              {r.nok_count} Not OK · {r.marginal_count} marginal
            </span>
          </div>
          {r.nc_ids.length > 0 && (
            <div className="mt-3 text-sm">
              Non-conformance:{' '}
              {r.nc_ids.map((ncId, i) => (
                <Link key={ncId} to={`/ncs/${ncId}`} className="mr-2 font-semibold text-red-800 underline">
                  {r.nc_nos[i]}
                </Link>
              ))}
            </div>
          )}
          {r.reinspection_of_report_id && (
            <div className="mt-2 text-sm">
              Re-inspection of{' '}
              <Link className="underline" to={`/reports/${r.reinspection_of_report_id}`}>
                an earlier report
              </Link>
            </div>
          )}
          {r.reinspected_by.length > 0 && (
            <div className="mt-2 text-sm">
              Re-inspected later:{' '}
              {r.reinspected_by.map((rid) => (
                <Link key={rid} className="mr-2 underline" to={`/reports/${rid}`}>
                  view
                </Link>
              ))}
            </div>
          )}
        </Card>
        <Card title="Times (IST)">
          <dl className="grid grid-cols-2 gap-y-1 text-sm">
            <dt className="text-slate-500">Measured on CMM</dt>
            <dd>{formatIst(r.measured_at, true)}</dd>
            <dt className="text-slate-500">Received</dt>
            <dd>{formatIst(r.received_at, true)}</dd>
            <dt className="text-slate-500">Ingested</dt>
            <dd>{formatIst(r.ingested_at, true)}</dd>
            <dt className="text-slate-500">Source</dt>
            <dd>{r.source}</dd>
            <dt className="text-slate-500">File</dt>
            <dd className="truncate" title={r.original_filename ?? ''}>
              {r.original_filename ?? 'manual entry'}
            </dd>
          </dl>
        </Card>
        <Card title={`Warnings (${r.warnings.length})`}>
          {r.warnings.length === 0 ? (
            <p className="text-sm text-slate-500">None.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {r.warnings.filter((w) => w.code !== 'PENDING_ROWS').map((w, i) => (
                <li key={i} className={w.code === 'FAILED' ? 'text-red-800' : 'text-amber-900'}>
                  <span className="mr-1 rounded bg-amber-100 px-1 text-[10px] font-semibold">{w.code}</span>
                  {w.message}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {r.status === 'NEEDS_CONFIRMATION' && <ConfirmRows report={r} />}
      <Card title="Characteristics: measured vs limits">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500 uppercase">
              <tr>
                <th className="py-2">Char</th>
                <th>Name</th>
                <th>Class</th>
                <th className="text-right">Nominal</th>
                <th className="text-right">LSL</th>
                <th className="text-right">USL</th>
                <th className="text-right">Actual</th>
                <th className="text-right">Dev</th>
                <th className="pl-4">Position in tolerance</th>
                <th>Result</th>
                <th>Limits</th>
              </tr>
            </thead>
            <tbody>
              {r.measurements.map((m) => (
                <tr key={m.id} className="border-t border-slate-100">
                  <td className="py-2 font-medium">{m.char_no}</td>
                  <td>{m.char_name}</td>
                  <td>
                    <SeverityChip severity={m.classification} />
                  </td>
                  <td className="text-right tabular-nums">{num(m.nominal)}</td>
                  <td className="text-right tabular-nums">{num(m.lsl)}</td>
                  <td className="text-right tabular-nums">{num(m.usl)}</td>
                  <td className="text-right font-semibold tabular-nums">{num(m.actual)}</td>
                  <td className="text-right tabular-nums">{num(m.deviation)}</td>
                  <td className="pl-4">
                    <LimitBar
                      actual={Number(m.actual)}
                      lsl={m.lsl !== null ? Number(m.lsl) : m.tolerance_type === 'UPPER_ONLY' ? 0 : null}
                      usl={m.usl !== null ? Number(m.usl) : null}
                      result={m.result}
                    />
                  </td>
                  <td>
                    <ResultChip result={m.result} suspect={m.is_suspect} />
                  </td>
                  <td className="text-xs text-slate-500">{m.limits_source === 'MASTER' ? 'master' : 'from report'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
