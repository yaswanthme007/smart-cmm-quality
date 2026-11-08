import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { api } from '../../api/client'
import type { NcDetail, TimelineEvent } from '../../api/types'
import { formatDate, formatIst, hours, ms, num } from '../../components/format'
import { Button, Card, ErrorBox, Field, inputClass, LimitBar, PageHeader, ResultChip, SeverityChip, StatusChip } from '../../components/ui'
import { useMe } from '../auth/useAuth'
import { SimilarNcs } from './SimilarNcs'

const SIX_M = ['MAN', 'MACHINE', 'METHOD', 'MATERIAL', 'MEASUREMENT', 'ENVIRONMENT']
const EDITABLE = ['ACKNOWLEDGED', 'IN_PROGRESS']

const KIND_DOT: Record<string, string> = {
  measured: 'bg-slate-400',
  received: 'bg-slate-500',
  'alert.nok': 'bg-red-600',
  'alert.recurrence': 'bg-orange-500',
  'alert.escalation': 'bg-violet-600',
  'email.sent': 'bg-sky-500',
  'nc.verify': 'bg-green-600',
  'nc.reject': 'bg-amber-600',
  'nc.cancel': 'bg-slate-600',
}

function Timeline({ id }: { id: string }) {
  const events = useQuery({ queryKey: ['timeline', id], queryFn: () => api.get<TimelineEvent[]>(`/ncs/${id}/timeline`) })
  return (
    <ol className="relative space-y-3 border-l-2 border-slate-200 pl-4">
      {events.data?.map((e, i) => (
        <li key={i} className="relative">
          <span className={`absolute top-1.5 -left-[23px] h-3 w-3 rounded-full ${KIND_DOT[e.kind] ?? 'bg-slate-700'}`} />
          <div className="text-sm font-medium">
            {e.title}
            {e.ms !== null && <span className="ml-2 rounded bg-slate-100 px-1.5 text-xs font-semibold text-slate-700">{ms(e.ms)} after file arrived</span>}
          </div>
          <div className="text-xs text-slate-500">
            {formatIst(e.at, true)}
            {e.actor && ` · ${e.actor}`}
          </div>
          {e.detail && <div className="mt-0.5 text-xs text-slate-600">{e.detail}</div>}
        </li>
      ))}
    </ol>
  )
}

function ActionForm({ nc: n, editable, onSaved }: { nc: NcDetail; editable: boolean; onSaved: () => void }) {
  const [form, setForm] = useState({
    containment: n.containment ?? '',
    root_cause_category: n.root_cause_category ?? '',
    root_cause: n.root_cause ?? '',
    corrective_action: n.corrective_action ?? '',
    preventive_action: n.preventive_action ?? '',
    target_date: n.target_date ?? '',
  })
  const save = useMutation({
    mutationFn: () => api.patch(`/ncs/${n.id}`, Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === '' ? null : v]))),
    onSuccess: onSaved,
  })
  return (
    <Card title="Corrective action (8D-style, light)">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Containment: what was done with suspect parts">
                <textarea className={inputClass} rows={2} disabled={!editable} value={form.containment} onChange={(e) => setForm({ ...form, containment: e.target.value })} />
              </Field>
              <Field label="Root cause (6M)">
                <select className={inputClass} disabled={!editable} value={form.root_cause_category} onChange={(e) => setForm({ ...form, root_cause_category: e.target.value })}>
                  <option value="">—</option>
                  {SIX_M.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </Field>
              <Field label="Root cause description">
                <textarea className={inputClass} rows={2} disabled={!editable} value={form.root_cause} onChange={(e) => setForm({ ...form, root_cause: e.target.value })} />
              </Field>
              <Field label="Corrective action">
                <textarea className={inputClass} rows={2} disabled={!editable} value={form.corrective_action} onChange={(e) => setForm({ ...form, corrective_action: e.target.value })} />
              </Field>
              <Field label="Preventive action (optional)">
                <textarea className={inputClass} rows={2} disabled={!editable} value={form.preventive_action} onChange={(e) => setForm({ ...form, preventive_action: e.target.value })} />
              </Field>
              <Field label="Target date">
                <input type="date" className={inputClass} disabled={!editable} value={form.target_date} onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
              </Field>
            </div>
            <ErrorBox error={save.error} />
            {editable && (
              <Button className="mt-3" onClick={() => save.mutate()} disabled={save.isPending}>
                Save actions
              </Button>
            )}
            {!n.can_work && n.status !== 'CLOSED' && n.status !== 'CANCELLED' && (
              <p className="mt-2 text-xs text-slate-500">Only the owner, their supervisor or the Quality Head can work this NC.</p>
            )}
            {n.status === 'OPEN' && n.can_work && <p className="mt-2 text-xs text-slate-500">Acknowledge first, then record the actions.</p>}
          </Card>
  )
}

export function NcDetailPage() {
  const { id = '' } = useParams()
  const me = useMe()
  const queryClient = useQueryClient()
  const nc = useQuery({ queryKey: ['nc', id], queryFn: () => api.get<NcDetail>(`/ncs/${id}`) })
  const n = nc.data
  const [note, setNote] = useState('')
  const [evidenceNote, setEvidenceNote] = useState('')

  const done = () => {
    void queryClient.invalidateQueries({ queryKey: ['nc', id] })
    void queryClient.invalidateQueries({ queryKey: ['timeline', id] })
    void queryClient.invalidateQueries({ queryKey: ['ncs'] })
    void queryClient.invalidateQueries({ queryKey: ['kpi'] })
  }
  const action = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api.post(`/ncs/${id}/${path}`, body),
    onSuccess: () => {
      setNote('')
      done()
    },
  })
  const evidence = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      if (evidenceNote) fd.append('note', evidenceNote)
      return api.post(`/ncs/${id}/evidence`, fd)
    },
    onSuccess: () => {
      setEvidenceNote('')
      done()
    },
  })

  if (nc.error) return <ErrorBox error={nc.error} />
  if (!n) return <div className="text-slate-500">Loading…</div>
  const isQh = me.data?.role === 'QUALITY_HEAD'
  const editable = n.can_work && EDITABLE.includes(n.status)
  const err = action.error ?? evidence.error

  return (
    <div className="space-y-4">
      <PageHeader
        title={n.nc_no}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <StatusChip status={n.status} />
            <SeverityChip severity={n.severity} />
            {n.escalation_level > 0 && <span className="rounded bg-violet-100 px-2 text-xs font-semibold text-violet-800">Escalated L{n.escalation_level}</span>}
            {n.overdue && <span className="rounded bg-amber-100 px-2 text-xs font-semibold text-amber-900">Overdue</span>}
            <span>
              {n.part_no} {n.part_name} · {n.machine_code} / {n.process_code} · owner {n.owner_name ?? '-'} · age {hours(n.age_hours)}
            </span>
          </span>
        }
        actions={
          <>
            {n.status === 'OPEN' && n.can_work && (
              <Button onClick={() => action.mutate({ path: 'acknowledge' })} disabled={action.isPending}>
                Acknowledge
              </Button>
            )}
            {n.status === 'IN_PROGRESS' && n.can_work && (
              <Button onClick={() => action.mutate({ path: 'submit' })} disabled={action.isPending}>
                Submit for verification
              </Button>
            )}
          </>
        }
      />
      <ErrorBox error={err} />
      {n.warnings.map((w) => (
        <div key={w.code} className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
          {w.message}
        </div>
      ))}
      {n.reinspection_ok_report && (
        <div className="rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-900">
          Re-inspection OK: <Link className="font-semibold underline" to={`/reports/${n.reinspection_ok_report.id}`}>{n.reinspection_ok_report.report_no}</Link> measured this part again
          and it is {n.reinspection_ok_report.part_result}. The Quality Head can cancel this NC as a measurement issue.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Measured vs limits">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-slate-500 uppercase">
                  <tr>
                    <th className="py-2">Report</th>
                    <th>SN</th>
                    <th>Char</th>
                    <th className="text-right">LSL</th>
                    <th className="text-right">USL</th>
                    <th className="text-right">Actual</th>
                    <th className="pl-4">Position</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {n.measurements.map((m) => (
                    <tr key={m.id} className="border-t border-slate-100">
                      <td className="py-2">
                        <Link className="underline" to={`/reports/${m.report_id}`}>
                          {m.report_no}
                        </Link>
                      </td>
                      <td>{m.serial_no}</td>
                      <td>
                        {m.char_no} <span className="text-slate-500">{m.char_name}</span>
                      </td>
                      <td className="text-right tabular-nums">{num(m.lsl)}</td>
                      <td className="text-right tabular-nums">{num(m.usl)}</td>
                      <td className="text-right font-semibold tabular-nums text-red-700">{num(m.actual)}</td>
                      <td className="pl-4">
                        <LimitBar actual={Number(m.actual)} lsl={m.lsl !== null ? Number(m.lsl) : 0} usl={m.usl !== null ? Number(m.usl) : null} result={m.result} />
                      </td>
                      <td>
                        <ResultChip result={m.result} suspect={m.is_suspect} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <ActionForm
            key={[n.status, n.containment, n.root_cause_category, n.root_cause, n.corrective_action, n.preventive_action, n.target_date].join('|')}
            nc={n}
            editable={editable}
            onSaved={done}
          />
          <Card title={`Evidence (${n.evidence.length})`}>
            <ul className="space-y-1 text-sm">
              {n.evidence.map((e) => (
                <li key={e.id}>
                  <a className="underline" href={`/api/ncs/${id}/evidence/${e.id}`}>
                    {e.filename}
                  </a>{' '}
                  <span className="text-xs text-slate-500">
                    {(e.size / 1024).toFixed(1)} KB · {formatIst(e.created_at)} {e.note && `· ${e.note}`}
                  </span>
                </li>
              ))}
            </ul>
            {editable && (
              <div className="mt-3 flex flex-wrap items-end gap-2">
                <Field label="Note">
                  <input className={inputClass} value={evidenceNote} onChange={(e) => setEvidenceNote(e.target.value)} placeholder="e.g. re-measurement after insert change" />
                </Field>
                <label className="cursor-pointer rounded-md border border-slate-300 bg-white px-4 py-2 text-sm hover:bg-slate-50">
                  {evidence.isPending ? 'Uploading…' : 'Add file (photo, PDF, CSV, max 10 MB)'}
                  <input type="file" className="sr-only" accept=".jpg,.jpeg,.png,.pdf,.csv,.txt,.xlsx" onChange={(e) => e.target.files?.[0] && evidence.mutate(e.target.files[0])} />
                </label>
              </div>
            )}
          </Card>

          {isQh && (n.status === 'PENDING_VERIFICATION' || n.status === 'OPEN' || n.status === 'ACKNOWLEDGED') && (
            <Card title="Quality Head decision">
              <Field label={n.status === 'PENDING_VERIFICATION' ? 'Verification note (required to reject)' : 'Cancel reason (required)'}>
                <textarea className={inputClass} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <div className="mt-3 flex flex-wrap gap-2">
                {n.status === 'PENDING_VERIFICATION' ? (
                  <>
                    <Button onClick={() => action.mutate({ path: 'verify', body: { approve: true, note: note || null } })}>Verify and close</Button>
                    <Button variant="danger" disabled={!note.trim()} onClick={() => action.mutate({ path: 'verify', body: { approve: false, note } })}>
                      Reject
                    </Button>
                  </>
                ) : (
                  <Button variant="secondary" disabled={!note.trim()} onClick={() => action.mutate({ path: 'cancel', body: { reason: note } })}>
                    Cancel NC
                  </Button>
                )}
              </div>
            </Card>
          )}
          {n.status === 'CLOSED' && (
            <Card title="Closed">
              <p className="text-sm">
                Verified {formatIst(n.verified_at, true)}. {n.verification_note}
              </p>
            </Card>
          )}
          {n.status === 'CANCELLED' && (
            <Card title="Cancelled">
              <p className="text-sm">{n.cancel_reason}</p>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card title="Timeline">
            <Timeline id={id} />
          </Card>
          <Card title="Key times">
            <dl className="grid grid-cols-2 gap-y-1 text-sm">
              <dt className="text-slate-500">Detected</dt>
              <dd>{formatIst(n.detected_at, true)}</dd>
              <dt className="text-slate-500">Acknowledged</dt>
              <dd>{formatIst(n.acknowledged_at, true)}</dd>
              <dt className="text-slate-500">Submitted</dt>
              <dd>{formatIst(n.submitted_at, true)}</dd>
              <dt className="text-slate-500">Closed</dt>
              <dd>{formatIst(n.closed_at, true)}</dd>
              <dt className="text-slate-500">Target date</dt>
              <dd>{formatDate(n.target_date)}</dd>
              <dt className="text-slate-500">Recurrences</dt>
              <dd>{n.recurrence_count}</dd>
            </dl>
          </Card>
          <SimilarNcs ncId={id} />
        </div>
      </div>
    </div>
  )
}
