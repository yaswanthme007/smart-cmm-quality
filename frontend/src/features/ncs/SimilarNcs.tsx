import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'

import { api, ApiError } from '../../api/client'
import { Card } from '../../components/ui'

interface Similar {
  id: string
  nc_no: string
  score: number
  root_cause_category: string | null
  root_cause: string | null
  corrective_action: string | null
}

/** Optional AI-assisted suggestions (Section 19). Hidden when the AI module is off. */
export function SimilarNcs({ ncId }: { ncId: string }) {
  const similar = useQuery({
    queryKey: ['nc', ncId, 'similar'],
    queryFn: () => api.get<Similar[]>(`/ncs/${ncId}/similar`),
    retry: (count, error) => !(error instanceof ApiError && [403, 404].includes(error.status)) && count < 1,
  })
  if (!similar.data || similar.data.length === 0) return null
  return (
    <Card title="Suggested from past NCs">
      <p className="mb-2 text-xs text-slate-500">Text similarity over closed NCs. Suggestions only; the owner decides.</p>
      <ul className="space-y-2 text-sm">
        {similar.data.map((s) => (
          <li key={s.id} className="rounded border border-slate-200 p-2">
            <Link to={`/ncs/${s.id}`} className="font-medium underline">
              {s.nc_no}
            </Link>{' '}
            <span className="text-xs text-slate-500">similarity {(s.score * 100).toFixed(0)}%</span>
            <div className="text-xs">
              {s.root_cause_category}: {s.root_cause}
            </div>
            <div className="text-xs text-slate-600">Action: {s.corrective_action}</div>
          </li>
        ))}
      </ul>
    </Card>
  )
}
