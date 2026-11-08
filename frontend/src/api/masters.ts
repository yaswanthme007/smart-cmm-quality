import { useQuery } from '@tanstack/react-query'

import { api } from './client'
import type { MasterRow } from './types'

export interface Option {
  id: string
  label: string
}

function useList(path: string, label: (row: MasterRow) => string) {
  return useQuery({
    queryKey: ['masters', path],
    queryFn: async () => (await api.get<MasterRow[]>(path)).map((row) => ({ id: row.id, label: label(row), row })),
    staleTime: 5 * 60_000,
  })
}

export const useParts = () => useList('/parts', (r) => `${r.part_no} ${r.name}`)
export const useMachines = () => useList('/machines', (r) => String(r.code))
export const useProcesses = () => useList('/processes', (r) => `${r.code} ${r.name}`)
export const usePeople = () => useList('/people', (r) => String(r.full_name))
