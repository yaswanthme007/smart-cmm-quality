import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, ApiError } from '../../api/client'
import type { MappingProfile, PreviewOut } from '../../api/types'
import { num } from '../../components/format'
import { Button, Card, ErrorBox, Field, inputClass, PageHeader, ResultChip } from '../../components/ui'
import { can, useMe } from '../auth/useAuth'

const FIELD_LABEL: Record<string, string> = {
  char_no: 'Characteristic no. *',
  char_name: 'Description',
  actual: 'Measured value *',
  nominal: 'Nominal',
  upper_tol: 'Upper tolerance',
  lower_tol: 'Lower tolerance',
  usl: 'Upper limit (USL)',
  lsl: 'Lower limit (LSL)',
  part_no: 'Part number (per row)',
}
const HEADER_KEYS = ['part_no', 'serial_no', 'machine_code', 'measured_at'] as const

const EMPTY: MappingProfile = {
  name: '',
  vendor: 'OTHER',
  file_kind: 'CSV',
  delimiter: ',',
  decimal_separator: '.',
  header_row: 1,
  column_map: {},
  header_fields: {
    part_no: { from: 'filename', regex: '^(?P<v>[A-Z]{2}\\d{3})_' },
    serial_no: { from: 'filename', regex: '_SN(?P<v>\\d+)' },
    machine_code: { from: 'upload_form' },
    measured_at: { from: 'file_mtime' },
  },
  unit: 'mm',
  is_active: true,
}

type ProfileWithId = MappingProfile & { id: string }

export function MappingPage() {
  const me = useMe()
  const queryClient = useQueryClient()
  const profiles = useQuery({ queryKey: ['mapping-profiles'], queryFn: () => api.get<ProfileWithId[]>('/mapping-profiles') })
  const [draft, setDraft] = useState<MappingProfile>(EMPTY)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<PreviewOut | null>(null)
  const [error, setError] = useState<unknown>(null)
  const isAdmin = can.masters(me.data?.role)

  const runPreview = async (profile: MappingProfile | null, sample: File | null = file) => {
    if (!sample) return
    const form = new FormData()
    form.append('file', sample)
    if (profile) form.append('profile', JSON.stringify(profile))
    setError(null)
    try {
      setPreview(await api.post<PreviewOut>('/mapping-profiles/preview', form))
    } catch (e) {
      setError(e)
    }
  }

  const save = useMutation({
    mutationFn: () => (editingId ? api.put(`/mapping-profiles/${editingId}`, draft) : api.post('/mapping-profiles', draft)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['mapping-profiles'] })
      setEditingId(null)
      setDraft(EMPTY)
      setPreview(null)
      setFile(null)
    },
  })

  const setColumn = (field: string, column: string) => {
    const column_map = { ...draft.column_map }
    if (column) column_map[field] = column
    else delete column_map[field]
    const next = { ...draft, column_map }
    setDraft(next)
    void runPreview(next)
  }
  const setHeader = (key: string, rule: MappingProfile['header_fields'][string] | null) => {
    const header_fields = { ...draft.header_fields }
    if (rule) header_fields[key] = rule
    else delete header_fields[key]
    const next = { ...draft, header_fields }
    setDraft(next)
    void runPreview(next)
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Mapping profiles"
        subtitle="A new CMM report layout is a configuration, not a code change: upload a sample, pick a column for each field, check the preview, save."
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Profiles">
          <ul className="space-y-2 text-sm">
            {profiles.data?.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2 rounded border border-slate-200 p-2">
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-slate-500">
                    {p.file_kind} · {p.vendor} {p.is_active ? '' : '· inactive'}
                  </div>
                </div>
                {isAdmin && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setEditingId(p.id)
                      setDraft(p)
                      void runPreview(p)
                    }}
                  >
                    Edit
                  </Button>
                )}
              </li>
            ))}
          </ul>
          {isAdmin && (
            <Button
              className="mt-3 w-full"
              variant="secondary"
              onClick={() => {
                setEditingId(null)
                setDraft(EMPTY)
                setPreview(null)
              }}
            >
              New profile
            </Button>
          )}
        </Card>

        <Card title={editingId ? `Edit: ${draft.name}` : 'New profile'} className="lg:col-span-2">
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="Name">
              <input className={inputClass} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. PC-DMIS CSV (CMM-03)" />
            </Field>
            <Field label="File kind">
              <select className={inputClass} value={draft.file_kind} onChange={(e) => setDraft({ ...draft, file_kind: e.target.value as MappingProfile['file_kind'] })}>
                {['CSV', 'TSV', 'XLSX', 'CALYPSO_CHR', 'AQDEF'].map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </Field>
            <Field label="Sample file">
              <input
                type="file"
                className={inputClass}
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null
                  setFile(f)
                  void runPreview(Object.keys(draft.column_map).length ? draft : null, f)
                }}
              />
            </Field>
            <Field label="Delimiter">
              <select className={inputClass} value={draft.delimiter ?? ','} onChange={(e) => setDraft({ ...draft, delimiter: e.target.value })}>
                <option value=",">comma ,</option>
                <option value=";">semicolon ;</option>
                <option value={'\t'}>tab</option>
              </select>
            </Field>
            <Field label="Decimal separator">
              <select className={inputClass} value={draft.decimal_separator} onChange={(e) => setDraft({ ...draft, decimal_separator: e.target.value })}>
                <option value=".">dot 1.234</option>
                <option value=",">comma 1,234 (German locale)</option>
              </select>
            </Field>
            <Field label="Header row / unit">
              <div className="flex gap-2">
                <input type="number" min={1} className={inputClass} value={draft.header_row} onChange={(e) => setDraft({ ...draft, header_row: Number(e.target.value) })} />
                <select className={inputClass} value={draft.unit} onChange={(e) => setDraft({ ...draft, unit: e.target.value })}>
                  <option value="mm">mm</option>
                  <option value="inch">inch</option>
                </select>
              </div>
            </Field>
          </div>
          <div className="mt-2">
            <Button variant="secondary" disabled={!file} onClick={() => void runPreview(null)}>
              Detect columns
            </Button>
          </div>

          {preview && preview.columns.length > 0 && (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <h3 className="mb-2 text-sm font-semibold">Columns → fields</h3>
                <div className="space-y-2">
                  {Object.keys(FIELD_LABEL).map((field) => (
                    <label key={field} className="flex items-center justify-between gap-2 text-sm">
                      <span>{FIELD_LABEL[field]}</span>
                      <select className={`${inputClass} max-w-52`} value={draft.column_map[field] ?? ''} onChange={(e) => setColumn(field, e.target.value)}>
                        <option value="">—</option>
                        {preview.columns.map((c) => (
                          <option key={c}>{c}</option>
                        ))}
                      </select>
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <h3 className="mb-2 text-sm font-semibold">Report header fields</h3>
                <div className="space-y-2">
                  {HEADER_KEYS.map((key) => {
                    const rule = draft.header_fields[key]
                    return (
                      <div key={key} className="rounded border border-slate-200 p-2 text-sm">
                        <div className="mb-1 font-medium">{key}</div>
                        <div className="flex gap-2">
                          <select
                            className={inputClass}
                            value={rule?.from ?? ''}
                            onChange={(e) => setHeader(key, e.target.value ? { from: e.target.value } : null)}
                          >
                            <option value="">not set</option>
                            <option value="filename">filename regex</option>
                            <option value="column">column</option>
                            <option value="upload_form">upload form</option>
                            <option value="file_mtime">file time</option>
                            <option value="const">fixed value</option>
                          </select>
                          {rule?.from === 'filename' && (
                            <input className={inputClass} value={rule.regex ?? ''} placeholder="(?P<v>…)" onChange={(e) => setHeader(key, { ...rule, regex: e.target.value })} />
                          )}
                          {rule?.from === 'column' && (
                            <select className={inputClass} value={rule.column ?? ''} onChange={(e) => setHeader(key, { ...rule, column: e.target.value })}>
                              <option value="">—</option>
                              {preview.columns.map((c) => (
                                <option key={c}>{c}</option>
                              ))}
                            </select>
                          )}
                          {rule?.from === 'const' && <input className={inputClass} value={rule.value ?? ''} onChange={(e) => setHeader(key, { ...rule, value: e.target.value })} />}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          )}

          <div className="mt-4 space-y-2">
            <ErrorBox error={error} />
            {preview?.error && <ErrorBox error={preview.error} />}
            {preview && Object.keys(preview.header).length > 0 && (
              <p className="text-sm text-slate-600">
                Detected: part <b>{preview.header.part_no ?? '-'}</b> · serial <b>{preview.header.serial_no ?? '-'}</b> · machine{' '}
                <b>{preview.header.machine_code ?? '(from upload form)'}</b>
              </p>
            )}
            {preview && preview.rows.length > 0 && (
              <div className="overflow-x-auto">
                <h3 className="mb-1 text-sm font-semibold">Preview: first {preview.rows.length} rows, classified</h3>
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-slate-500 uppercase">
                    <tr>
                      <th className="py-1">Char</th>
                      <th>Name</th>
                      <th className="text-right">LSL</th>
                      <th className="text-right">USL</th>
                      <th className="text-right">Actual</th>
                      <th>Result</th>
                      <th>Limits</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((r) => (
                      <tr key={r.char_no} className="border-t border-slate-100">
                        <td className="py-1">{r.char_no}</td>
                        <td>{r.char_name}</td>
                        <td className="text-right">{num(r.lsl)}</td>
                        <td className="text-right">{num(r.usl)}</td>
                        <td className="text-right font-medium">{num(r.actual)}</td>
                        <td>
                          <ResultChip result={r.result} />
                        </td>
                        <td className="text-xs text-slate-500">{r.limits_source.toLowerCase()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {isAdmin ? (
              <div className="flex gap-2">
                <Button disabled={!draft.name || !draft.column_map.char_no || !draft.column_map.actual || save.isPending} onClick={() => save.mutate()}>
                  {editingId ? 'Save changes' : 'Save profile'}
                </Button>
                {save.error instanceof ApiError && <ErrorBox error={save.error} />}
              </div>
            ) : (
              <p className="text-xs text-slate-500">Only Admin can save profiles. Anyone can preview a file.</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
