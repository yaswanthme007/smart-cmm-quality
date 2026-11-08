import { useQuery } from '@tanstack/react-query'

import { api, ApiError } from '../../api/client'
import type { Role, User } from '../../api/types'

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: () => api.get<User>('/auth/me'),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 1,
    staleTime: 60_000,
  })
}

/** Permission matrix (Section 14.1). The UI only hides buttons; the server enforces. */
export const can = {
  upload: (r?: Role) => r === 'INSPECTOR' || r === 'QUALITY_HEAD' || r === 'ADMIN',
  verify: (r?: Role) => r === 'QUALITY_HEAD',
  baseline: (r?: Role) => r === 'QUALITY_HEAD',
  masters: (r?: Role) => r === 'ADMIN',
  settings: (r?: Role) => r === 'QUALITY_HEAD' || r === 'ADMIN',
  audit: (r?: Role) => r === 'QUALITY_HEAD' || r === 'ADMIN',
  workNc: (r?: Role) => r === 'PROCESS_OWNER' || r === 'SUPERVISOR' || r === 'QUALITY_HEAD',
}
