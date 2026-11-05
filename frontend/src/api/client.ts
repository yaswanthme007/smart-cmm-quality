/** Minimal typed fetch wrapper. Same-origin /api, cookies included for auth. */

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`API request failed with status ${status}`)
    this.status = status
    this.body = body
  }
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { credentials: 'include', ...init })
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, body)
  return body as T
}

export type CheckStatus = 'ok' | 'error' | 'not_configured'

export interface Health {
  status: 'ok' | 'degraded'
  db: CheckStatus
  worker: CheckStatus
  smtp: CheckStatus
  demo_mode: boolean
}

/** /health answers 503 with a body when degraded; we still want that body. */
export async function getHealth(): Promise<Health> {
  try {
    return await apiGet<Health>('/health')
  } catch (error) {
    if (error instanceof ApiError && error.status === 503 && error.body) {
      return error.body as Health
    }
    throw error
  }
}
