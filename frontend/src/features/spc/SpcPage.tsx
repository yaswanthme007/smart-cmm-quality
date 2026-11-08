import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useSearchParams } from 'react-router'

import { api, qs } from '../../api/client'
import type { SpcChart, SpcStream } from '../../api/types'
import { Chart } from '../../components/Chart'
import { formatIst } from '../../components/format'
import { Button, Card, Empty, ErrorBox, inputClass, PageHeader, SeverityChip } from '../../components/ui'
import { can, useMe } from '../auth/useAuth'

const RULE_COLOR: Record<string, string> = { N1: '#b91c1c', N2: '#7c3aed', N3: '#c2410c', N5: '#db2777' }

function fmt(v: number | null | undefined, d = 2) {
  return v === null || v === undefined ? '-' : v.toFixed(d)
}

export function SpcPage() {
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const queryClient = useQueryClient()
  const streams = useQuery({ queryKey: ['spc', 'streams'], queryFn: () => api.get<SpcStream[]>('/spc/streams') })
  const charId = params.get('characteristic_id')
  const machineId = params.get('machine_id')
  const selected = streams.data?.find((s) => s.characteristic_id === charId && s.machine_id === machineId)
  const fallback = streams.data?.find((s) => s.active_signals.includes('N3')) ?? streams.data?.[0]
  const current = selected ?? fallback
  const chart = useQuery({
    queryKey: ['spc', 'chart', current?.characteristic_id, current?.machine_id],
    queryFn: () => api.get<SpcChart>(`/spc/characteristics/${current!.characteristic_id}${qs({ machine_id: current!.machine_id, limit: 120 })}`),
    enabled: Boolean(current),
  })
  const baseline = useMutation({
    mutationFn: () => api.post(`/spc/characteristics/${current!.characteristic_id}/baseline`, { machine_id: current!.machine_id }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['spc'] }),
  })
  const c = chart.data
  const d = c?.characteristic.decimals ?? 3

  const iOption = useMemo(() => {
    if (!c) return {}
    const xs = c.points.map((p) => formatIst(p.measured_at))
    const n = c.points.length
    const limitSeries = (name: string, value: number | null | undefined, color: string, dashed: boolean, width = 1.5) =>
      value === null || value === undefined
        ? []
        : [
            {
              name: `${name} ${value.toFixed(d + 1)}`,
              type: 'line',
              data: Array(n).fill(value),
              symbol: 'none',
              silent: true,
              lineStyle: { color, width, type: dashed ? 'dashed' : 'solid' },
              endLabel: { show: true, formatter: '{a}', color, fontSize: 10 },
              tooltip: { show: false },
              z: 1,
            },
          ]
    const limitLines = [
      ...limitSeries('USL', c.characteristic.usl, '#b91c1c', false, 2),
      ...limitSeries('UCL', c.limits?.ucl, '#334155', true),
      ...limitSeries('x̄', c.limits?.center, '#334155', false, 1),
      ...limitSeries('LCL', c.limits?.lcl, '#334155', true),
      ...limitSeries('LSL', c.characteristic.lsl, '#b91c1c', false, 2),
    ]
    const marked = new Map<number, string[]>()
    c.marks.forEach((m) => marked.set(m.index, [...(marked.get(m.index) ?? []), m.rule]))
    const values = c.points.map((p) => p.value)
    const bounds = [...values, c.limits?.ucl, c.limits?.lcl, c.characteristic.usl, c.characteristic.lsl].filter((v): v is number => typeof v === 'number')
    const span = Math.max(...bounds) - Math.min(...bounds) || 1
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 70, right: 120, top: 20, bottom: 60 },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 10 }],
      xAxis: { type: 'category', data: xs, axisLabel: { fontSize: 10 } },
      yAxis: { type: 'value', scale: true, min: Math.min(...bounds) - span * 0.08, max: Math.max(...bounds) + span * 0.08, axisLabel: { formatter: (v: number) => v.toFixed(d) } },
      series: [
        {
          name: c.characteristic.char_no,
          type: 'line',
          data: c.points.map((p, i) => ({
            value: p.value,
            symbolSize: marked.has(i) || p.result !== 'OK' ? 10 : 5,
            itemStyle: {
              color: p.result === 'NOK' ? '#b91c1c' : marked.has(i) ? RULE_COLOR[marked.get(i)![0]] ?? '#c2410c' : p.result === 'MARGINAL' ? '#d97706' : '#0f172a',
            },
          })),
          lineStyle: { color: '#475569', width: 1.5 },
          z: 3,
        },
        ...limitLines,
      ],
    }
  }, [c, d])

  const mrOption = useMemo(() => {
    if (!c) return {}
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 70, right: 110, top: 10, bottom: 25 },
      xAxis: { type: 'category', data: c.points.map((p) => formatIst(p.measured_at)), axisLabel: { show: false } },
      yAxis: { type: 'value', axisLabel: { formatter: (v: number) => v.toFixed(d) } },
      series: [
        {
          type: 'line',
          data: c.points.map((p) => p.mr),
          itemStyle: { color: '#475569' },
          symbolSize: 4,
          markLine: c.limits
            ? {
                symbol: 'none',
                data: [
                  { yAxis: c.limits.ucl_mr, label: { formatter: `UCL ${c.limits.ucl_mr.toFixed(d + 1)}` }, lineStyle: { type: 'dashed', color: '#334155' } },
                  { yAxis: c.limits.mr_bar, label: { formatter: `MR̄ ${c.limits.mr_bar.toFixed(d + 1)}` }, lineStyle: { color: '#334155' } },
                ],
                label: { position: 'end', fontSize: 10 },
              }
            : undefined,
        },
      ],
    }
  }, [c, d])

  const activeSignals = c?.signals.filter((s) => s.status === 'ACTIVE') ?? []

  return (
    <div className="space-y-4">
      <PageHeader title="SPC: control charts" subtitle="Individuals and moving-range (I-MR) charts with frozen baseline limits. Nelson rules warn before parts fail." />
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-xs text-slate-600">
          Stream (characteristic on machine)
          <select
            className={`${inputClass} mt-1 min-w-96`}
            value={current ? `${current.characteristic_id}|${current.machine_id}` : ''}
            onChange={(e) => {
              const [cid, mid] = e.target.value.split('|')
              setParams({ characteristic_id: cid, machine_id: mid })
            }}
          >
            {streams.data?.map((s) => (
              <option key={`${s.characteristic_id}|${s.machine_id}`} value={`${s.characteristic_id}|${s.machine_id}`}>
                {s.part_no} {s.char_no} {s.name} · {s.machine_code} ({s.points} pts){s.active_signals.length ? ` ⚠ ${s.active_signals.join(',')}` : ''}
              </option>
            ))}
          </select>
        </label>
        {can.baseline(me.data?.role) && current && (
          <Button variant="secondary" onClick={() => baseline.mutate()} disabled={baseline.isPending} title="Quality Head: recalculate frozen limits from conforming readings (audited)">
            Recalculate baseline
          </Button>
        )}
      </div>
      <ErrorBox error={baseline.error} />
      {!current && <Empty>No measurement streams yet.</Empty>}
      {c && (
        <div className="grid gap-4 lg:grid-cols-4">
          <Card
            className="lg:col-span-3"
            title={
              <span className="flex items-center gap-2">
                {c.characteristic.part_no} {c.characteristic.char_no} {c.characteristic.name} on {current?.machine_code} <SeverityChip severity={c.characteristic.classification} />
              </span>
            }
          >
            <Chart option={iOption} height={340} />
            <div className="mt-1 text-xs font-medium text-slate-500">Moving range</div>
            <Chart option={mrOption} height={140} />
            <p className="mt-2 text-xs text-slate-500">
              Red solid lines: drawing limits (USL/LSL). Dashed: control limits (process voice, x̄ ± 2.66·MR̄) frozen from {c.limits?.n_baseline ?? 0} baseline readings
              {c.limits?.baseline_from && ` (${formatIst(c.limits.baseline_from)} – ${formatIst(c.limits.baseline_to)})`}. Coloured points trigger a rule.
            </p>
          </Card>
          <div className="space-y-4">
            <Card title="Signals">
              {activeSignals.length === 0 && <p className="text-sm text-green-700">In control: no active signals.</p>}
              <ul className="space-y-2 text-sm">
                {c.signals.slice(0, 8).map((s) => (
                  <li key={s.id} className={s.status === 'ACTIVE' ? '' : 'opacity-60'}>
                    <span className="mr-1 rounded px-1.5 text-xs font-bold text-white" style={{ background: RULE_COLOR[s.rule] ?? '#475569' }}>
                      {s.rule}
                    </span>
                    <span className="text-xs font-semibold">{s.status}</span>
                    <div className="text-xs text-slate-600">{s.description}</div>
                    <div className="text-xs text-slate-400">{formatIst(s.triggered_at)}</div>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title="Capability">
              {!c.capability.valid && (
                <div className="mb-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs font-medium text-amber-900">{c.capability.message}</div>
              )}
              <dl className={`grid grid-cols-2 gap-y-1 text-sm ${c.capability.valid ? '' : 'opacity-40'}`}>
                <dt>Cp</dt>
                <dd className="text-right tabular-nums">{c.capability.valid ? fmt(c.capability.cp) : '-'}</dd>
                <dt>Cpk</dt>
                <dd className="text-right font-semibold tabular-nums">{c.capability.valid ? fmt(c.capability.cpk) : '-'}</dd>
                <dt>Pp</dt>
                <dd className="text-right tabular-nums">{c.capability.valid ? fmt(c.capability.pp) : '-'}</dd>
                <dt>Ppk</dt>
                <dd className="text-right tabular-nums">{c.capability.valid ? fmt(c.capability.ppk) : '-'}</dd>
                <dt>Readings</dt>
                <dd className="text-right tabular-nums">{c.capability.n}</dd>
                <dt>σ within</dt>
                <dd className="text-right tabular-nums">{c.limits ? c.limits.sigma_within.toFixed(d + 2) : '-'}</dd>
              </dl>
              <p className="mt-2 text-xs text-slate-500">Shown only with ≥ 30 readings and no active signals.</p>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
