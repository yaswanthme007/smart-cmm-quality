import { useQuery } from '@tanstack/react-query'

import { getHealth, type CheckStatus } from '../../api/client'

const statusLabel: Record<CheckStatus, string> = {
  ok: 'OK',
  error: 'Down',
  not_configured: 'Not configured',
}

const statusClass: Record<CheckStatus, string> = {
  ok: 'text-result-ok',
  error: 'text-result-nok',
  not_configured: 'text-slate-500',
}

/** Placeholder until the KPI dashboard (C22). Shows backend health so `make up` is verifiable. */
export function DashboardPage() {
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 10_000 })

  return (
    <section>
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="mt-1 text-slate-600">
        CMM quality alerts and corrective-action tracking. KPI tiles arrive in a later phase.
      </p>

      <div className="mt-6 max-w-sm rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="font-medium">System health</h2>
        {health.isPending && <p className="mt-2 text-slate-500">Checking…</p>}
        {health.isError && <p className="mt-2 text-result-nok">API unreachable</p>}
        {health.data && (
          <dl className="mt-2 grid grid-cols-2 gap-y-1 text-sm">
            {(['db', 'worker', 'smtp'] as const).map((key) => (
              <div key={key} className="contents">
                <dt className="uppercase text-slate-500">{key}</dt>
                <dd className={statusClass[health.data[key]]}>{statusLabel[health.data[key]]}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </section>
  )
}
