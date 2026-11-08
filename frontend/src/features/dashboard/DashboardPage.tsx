import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { Link, useNavigate } from 'react-router'

import { api, qs } from '../../api/client'
import type { AlertPage, ByRow, Filters, KpiSummary, ParetoRow, TrendPoint } from '../../api/types'
import { Chart } from '../../components/Chart'
import { FiltersBar } from '../../components/FiltersBar'
import { useFilters } from '../../components/useFilters'
import { hours, ms, pct, relativeTime } from '../../components/format'
import { Card, Empty, PageHeader, StatTile } from '../../components/ui'
import { KPI_HINTS } from './kpiHints'

function useKpi<T>(path: string, filters: Filters, extra: Record<string, string> = {}) {
  return useQuery({
    queryKey: ['kpi', path, filters, extra],
    queryFn: () => api.get<T>(`${path}${qs({ ...filters, ...extra })}`),
    refetchInterval: 30_000,
  })
}

const NOK_RED = '#b91c1c'

export function DashboardPage() {
  const [filters, setFilters] = useFilters()
  const navigate = useNavigate()
  const summary = useKpi<KpiSummary>('/kpi/summary', filters)
  const trend = useKpi<TrendPoint[]>('/kpi/trends', filters, { granularity: 'day' })
  const byMachine = useKpi<ByRow[]>('/kpi/by', filters, { group_by: 'machine' })
  const byPart = useKpi<ByRow[]>('/kpi/by', filters, { group_by: 'part' })
  const pareto = useKpi<ParetoRow[]>('/kpi/pareto', filters)
  const feed = useQuery({ queryKey: ['alerts', 'feed'], queryFn: () => api.get<AlertPage>('/alerts?mine=false&limit=12') })
  const s = summary.data
  const f = qs(filters as Record<string, string>)
  const drill = (extra: Record<string, string>) => `${qs({ ...filters, ...extra })}`

  const trendOption = useMemo(
    () => ({
      tooltip: { trigger: 'axis' },
      legend: { data: ['Inspected', 'Not OK %'], top: 0, right: 10 },
      grid: { left: 40, right: 50, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: trend.data?.map((t) => t.bucket.slice(5)) ?? [] },
      yAxis: [
        { type: 'value', name: 'parts' },
        { type: 'value', name: '%', min: 0, axisLabel: { formatter: '{value}%' } },
      ],
      series: [
        { name: 'Inspected', type: 'bar', data: trend.data?.map((t) => t.inspected) ?? [], itemStyle: { color: '#cbd5e1' } },
        { name: 'Not OK %', type: 'line', yAxisIndex: 1, data: trend.data?.map((t) => t.nok_pct ?? 0) ?? [], itemStyle: { color: NOK_RED }, smooth: true },
      ],
    }),
    [trend.data],
  )
  const barOption = (rows: ByRow[] | undefined) => ({
    tooltip: { trigger: 'axis' },
    grid: { left: 70, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'value', name: 'Not OK' },
    yAxis: { type: 'category', data: rows?.map((r) => r.group) ?? [] },
    series: [
      {
        type: 'bar',
        data: rows?.map((r) => r.nok) ?? [],
        itemStyle: { color: NOK_RED },
        label: { show: true, position: 'right', formatter: (p: { dataIndex: number }) => pct(rows?.[p.dataIndex]?.nok_pct) },
      },
    ],
  })
  const machineOption = useMemo(() => barOption(byMachine.data), [byMachine.data])
  const partOption = useMemo(() => barOption(byPart.data), [byPart.data])
  const paretoOption = useMemo(
    () => ({
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 45, top: 20, bottom: 60 },
      xAxis: { type: 'category', data: pareto.data?.map((p) => p.label) ?? [], axisLabel: { rotate: 35, fontSize: 10 } },
      yAxis: [{ type: 'value' }, { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } }],
      series: [
        { name: 'Not OK', type: 'bar', data: pareto.data?.map((p) => p.count) ?? [], itemStyle: { color: NOK_RED } },
        { name: 'Cumulative %', type: 'line', yAxisIndex: 1, data: pareto.data?.map((p) => p.cumulative_pct) ?? [], itemStyle: { color: '#334155' } },
      ],
    }),
    [pareto.data],
  )
  const ageOption = useMemo(
    () => ({
      grid: { left: 40, right: 10, top: 10, bottom: 30 },
      tooltip: {},
      xAxis: { type: 'category', data: s?.ageing.map((a) => a.bucket) ?? [] },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{ type: 'bar', data: s?.ageing.map((a) => a.count) ?? [], itemStyle: { color: '#c2410c' } }],
    }),
    [s?.ageing],
  )

  return (
    <div>
      <PageHeader
        title="Quality dashboard"
        subtitle="Live CMM results, alerts and corrective actions. Every number links to the records behind it."
        actions={
          <a className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50" href={`/api/exports/kpi.xlsx${f}`}>
            Export Excel
          </a>
        }
      />
      <FiltersBar filters={filters} onChange={setFilters} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <StatTile label="Inspected" value={s?.k1.inspected ?? '-'} to={`/reports${drill({})}`} hint={KPI_HINTS.K1} />
        <StatTile label="OK" value={s?.k1.ok ?? '-'} tone="ok" sub={`incl. ${s?.k1.marginal ?? 0} marginal`} to={`/reports${drill({ result: 'OK' })}`} hint={KPI_HINTS.K1} />
        <StatTile label="Not OK" value={s?.k1.nok ?? '-'} tone="nok" to={`/reports${drill({ result: 'NOK' })}`} hint={KPI_HINTS.K1} />
        <StatTile label="OK %" value={pct(s?.k2.ok_pct)} tone="ok" sub={`Not OK ${pct(s?.k2.nok_pct)}`} hint={KPI_HINTS.K2} />
        <StatTile label="Alert time (median)" value={ms(s?.k3.median_ms)} sub={`p95 ${ms(s?.k3.p95_ms)} · ${s?.k3.count ?? 0} alerts`} to="/alerts?view=times" hint={KPI_HINTS.K3} />
        <StatTile label="Open actions" value={s?.k4.open ?? '-'} tone={s?.k4.open ? 'nok' : 'default'} sub={`${s?.k4.escalated_open ?? 0} escalated`} to="/ncs?bucket=open" hint={KPI_HINTS.K4} />
        <StatTile label="Pending / Closed" value={`${s?.k4.pending ?? '-'} / ${s?.k4.closed ?? '-'}`} sub={`${s?.k4.overdue ?? 0} overdue · ${s?.k4.cancelled ?? 0} cancelled`} to="/ncs?bucket=pending" tone={s?.k4.overdue ? 'warn' : 'default'} hint={KPI_HINTS.K4} />
        <StatTile label="Closure lead time" value={hours(s?.k5.median_h)} sub={`p90 ${hours(s?.k5.p90_h)} · ack ${s?.k5.ack_median_min ?? '-'} min`} to="/ncs?bucket=closed" hint={KPI_HINTS.K5} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Not OK % by day (K6)" className="lg:col-span-2">
          {trend.data?.length ? <Chart option={trendOption} /> : <Empty>No inspections in this period.</Empty>}
        </Card>
        <Card title="Live alert feed" actions={<Link to="/alerts" className="text-xs underline">All</Link>}>
          <ul className="max-h-[260px] space-y-2 overflow-y-auto text-sm">
            {feed.data?.items.map((a) => (
              <li key={a.id} className="border-l-4 border-red-300 pl-2" style={{ borderColor: a.kind === 'SPC_WARNING' ? '#f59e0b' : a.kind === 'ESCALATION' ? '#7c3aed' : undefined }}>
                <Link to={a.nc_id ? `/ncs/${a.nc_id}` : `/spc`} className="font-medium hover:underline">
                  {a.title}
                </Link>
                <div className="text-xs text-slate-500">
                  {relativeTime(a.created_at)} · to {a.recipient_name ?? '-'}
                  {a.generation_ms !== null && ` · ${ms(a.generation_ms)}`}
                </div>
              </li>
            ))}
            {feed.data?.items.length === 0 && <Empty>No alerts yet.</Empty>}
          </ul>
        </Card>
        <Card title="Not OK by machine">
          <Chart option={machineOption} height={220} onClick={(p) => byMachine.data && navigate(`/reports${drill({ machine_id: byMachine.data[p.dataIndex].id, result: 'NOK' })}`)} />
        </Card>
        <Card title="Not OK by part">
          <Chart option={partOption} height={220} onClick={(p) => byPart.data && navigate(`/reports${drill({ part_id: byPart.data[p.dataIndex].id, result: 'NOK' })}`)} />
        </Card>
        <Card title="Open NC ageing">
          <Chart option={ageOption} height={220} onClick={() => navigate('/ncs?bucket=open')} />
        </Card>
        <Card title="Pareto of Not OK characteristics" className="lg:col-span-2">
          {pareto.data?.length ? <Chart option={paretoOption} /> : <Empty>No Not OK characteristics in this period.</Empty>}
        </Card>
        <Card title="Speed of the loop">
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-slate-500">Alert generation p95</dt>
            <dd className="text-right font-medium">{ms(s?.k3.p95_ms)}</dd>
            <dt className="text-slate-500">Email handed to SMTP (median)</dt>
            <dd className="text-right font-medium">{ms(s?.k3.email_median_ms)}</dd>
            <dt className="text-slate-500">Report latency (CMM → system)</dt>
            <dd className="text-right font-medium">{s?.k3b.median_s != null ? `${s.k3b.median_s} s` : '-'}</dd>
            <dt className="text-slate-500">Closed by target date</dt>
            <dd className="text-right font-medium">{pct(s?.k5.closed_on_time_pct)}</dd>
            <dt className="text-slate-500">Characteristic Not OK %</dt>
            <dd className="text-right font-medium">{pct(s?.k2.characteristic_nok_pct)}</dd>
          </dl>
          <p className="mt-3 text-xs text-slate-500">Measured from stored timestamps, not targets.</p>
        </Card>
      </div>
    </div>
  )
}
