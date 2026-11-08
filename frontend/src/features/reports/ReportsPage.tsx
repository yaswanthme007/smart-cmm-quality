import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type DragEvent } from 'react'
import { Link, useSearchParams } from 'react-router'

import { api, qs, upload } from '../../api/client'
import { useMachines } from '../../api/masters'
import type { MappingProfile, Page, Report, ReportDetail } from '../../api/types'
import { formatIst, relativeTime } from '../../components/format'
import { Button, Card, Empty, ErrorBox, Field, inputClass, PageHeader, ResultChip } from '../../components/ui'
import { can, useMe } from '../auth/useAuth'

type UploadOutcome = { kind: 'ok'; report: ReportDetail } | { kind: 'duplicate'; reportId: string; message: string } | { kind: 'failed'; report: ReportDetail }

function UploadCard() {
  const machines = useMachines()
  const profiles = useQuery({ queryKey: ['mapping-profiles'], queryFn: () => api.get<(MappingProfile & { id: string })[]>('/mapping-profiles') })
  const [machineId, setMachineId] = useState('')
  const [profileId, setProfileId] = useState('')
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)
  const [outcome, setOutcome] = useState<UploadOutcome | null>(null)
  const [error, setError] = useState<unknown>(null)
  const queryClient = useQueryClient()

  const send = async (file: File) => {
    setBusy(true)
    setError(null)
    setOutcome(null)
    const form = new FormData()
    form.append('file', file)
    if (machineId) form.append('machine_id', machineId)
    if (profileId) form.append('mapping_profile_id', profileId)
    try {
      const isPdf = file.name.toLowerCase().endsWith('.pdf')
      const { status, body } = await upload<ReportDetail & { detail?: string; report_id?: string }>(isPdf ? '/ai/extract-pdf' : '/reports/upload', form)
      if (status === 409) setOutcome({ kind: 'duplicate', reportId: body.report_id ?? '', message: body.detail ?? 'Duplicate' })
      else if (status === 422) setOutcome({ kind: 'failed', report: body })
      else setOutcome({ kind: 'ok', report: body })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDrag(false)
    const file = e.dataTransfer.files[0]
    if (file) void send(file)
  }

  return (
    <Card title="Upload CMM report">
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Machine (if not in the file)">
          <select className={inputClass} value={machineId} onChange={(e) => setMachineId(e.target.value)}>
            <option value="">From file / filename</option>
            {machines.data?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Mapping profile">
          <select className={inputClass} value={profileId} onChange={(e) => setProfileId(e.target.value)}>
            <option value="">Detect automatically</option>
            {profiles.data
              ?.filter((p) => p.is_active)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
        </Field>
      </div>
      <label
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={`mt-3 flex min-h-28 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-4 text-center text-sm ${drag ? 'border-slate-800 bg-slate-50' : 'border-slate-300'}`}
      >
        <input type="file" className="sr-only" accept=".csv,.xlsx,.txt,.tsv,.dfq,.pdf" onChange={(e) => e.target.files?.[0] && void send(e.target.files[0])} />
        <span className="font-medium">{busy ? 'Uploading and checking…' : 'Drop a file here or click to choose'}</span>
        <span className="mt-1 text-xs text-slate-500">CSV, XLSX, TSV, CALYPSO-style _chr.txt, AQDEF .dfq, PDF (table) · max 20 MB</span>
      </label>
      <div className="mt-3 space-y-2">
        <ErrorBox error={error} />
        {outcome?.kind === 'duplicate' && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
            {outcome.message}.{' '}
            <Link className="underline" to={`/reports/${outcome.reportId}`}>
              Open existing report
            </Link>
          </div>
        )}
        {outcome?.kind === 'failed' && (
          <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
            <div className="font-semibold">Could not ingest {outcome.report.report_no}</div>
            <ul className="mt-1 list-disc pl-5">
              {(outcome.report.errors ?? outcome.report.warnings.map((w) => w.message)).map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </div>
        )}
        {outcome?.kind === 'ok' && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
            {outcome.report.status === 'NEEDS_CONFIRMATION' ? (
              <span className="font-semibold text-amber-800">AI-extracted: needs confirmation</span>
            ) : (
              <ResultChip result={outcome.report.part_result} />
            )}
            <span>
              {outcome.report.report_no} · {outcome.report.part_no} SN {outcome.report.serial_no ?? '-'} · {outcome.report.machine_code}
            </span>
            {outcome.report.nc_nos.length > 0 && <span className="font-semibold text-red-800">Raised {outcome.report.nc_nos.join(', ')}</span>}
            {outcome.report.warnings.length > 0 && <span className="text-amber-800">{outcome.report.warnings.length} warning(s)</span>}
            <Link className="underline" to={`/reports/${outcome.report.id}`}>
              Details
            </Link>
          </div>
        )}
      </div>
    </Card>
  )
}

export function ReportsPage() {
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const filters = Object.fromEntries(params.entries())
  const offset = Number(params.get('offset') ?? 0)
  const reports = useQuery({
    queryKey: ['reports', filters],
    queryFn: () => api.get<Page<Report>>(`/reports${qs({ ...filters, limit: 50 })}`),
  })
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('offset')
    setParams(next)
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Inspection reports" subtitle="Every CMM result file, its verdict and any non-conformance it raised." />
      {can.upload(me.data?.role) && <UploadCard />}
      <Card
        title={`Reports (${reports.data?.total ?? 0})`}
        actions={
          <div className="flex gap-2">
            <select className={inputClass} value={params.get('result') ?? ''} onChange={(e) => setFilter('result', e.target.value)} aria-label="Result filter">
              <option value="">All results</option>
              <option value="OK">OK</option>
              <option value="MARGINAL">Marginal</option>
              <option value="NOK">Not OK</option>
            </select>
            <select className={inputClass} value={params.get('status') ?? ''} onChange={(e) => setFilter('status', e.target.value)} aria-label="Status filter">
              <option value="">All statuses</option>
              <option value="INGESTED">Ingested</option>
              <option value="FAILED">Failed</option>
            </select>
          </div>
        }
      >
        {reports.data?.items.length === 0 ? (
          <Empty>No reports match.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500 uppercase">
                <tr>
                  <th className="py-2">Report</th>
                  <th>Result</th>
                  <th>Part / serial</th>
                  <th>Machine</th>
                  <th>Measured (IST)</th>
                  <th>Received</th>
                  <th>Source</th>
                  <th>Warnings</th>
                </tr>
              </thead>
              <tbody>
                {reports.data?.items.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="py-2">
                      <Link to={`/reports/${r.id}`} className="font-medium underline-offset-2 hover:underline">
                        {r.report_no}
                      </Link>
                    </td>
                    <td>{r.status === 'FAILED' ? <span className="text-xs font-semibold text-red-700">FAILED</span> : <ResultChip result={r.part_result} />}</td>
                    <td>
                      {r.part_no ?? '-'} <span className="text-slate-500">SN {r.serial_no ?? '-'}</span>
                    </td>
                    <td>{r.machine_code ?? '-'}</td>
                    <td>{formatIst(r.measured_at)}</td>
                    <td title={formatIst(r.received_at, true)}>{relativeTime(r.received_at)}</td>
                    <td className="text-xs">{r.source.replace('_', ' ').toLowerCase()}</td>
                    <td>{r.warnings.length > 0 && <span className="text-xs text-amber-800">{r.warnings.length}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="secondary" disabled={offset === 0} onClick={() => setFilter('offset', String(Math.max(0, offset - 50)))}>
            Previous
          </Button>
          <Button variant="secondary" disabled={!reports.data || offset + 50 >= reports.data.total} onClick={() => setFilter('offset', String(offset + 50))}>
            Next
          </Button>
        </div>
      </Card>
    </div>
  )
}
