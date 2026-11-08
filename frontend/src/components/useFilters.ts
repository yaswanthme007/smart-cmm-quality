import { useSearchParams } from 'react-router'

import type { Filters } from '../api/types'

const KEYS: (keyof Filters)[] = ['date_from', 'date_to', 'part_id', 'machine_id', 'process_id', 'shift']

/** Filters live in the URL so every view is linkable (and survives reloads). */
export function useFilters(): [Filters, (patch: Partial<Filters>) => void] {
  const [params, setParams] = useSearchParams()
  const filters: Filters = {}
  for (const key of KEYS) {
    const value = params.get(key)
    if (value) filters[key] = value
  }
  const update = (patch: Partial<Filters>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next, { replace: true })
  }
  return [filters, update]
}
