/** Typed fetch wrapper. Same-origin /api, session cookie included (httpOnly, SameSite=Strict). */

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(errorMessage(status, body))
    this.status = status
    this.body = body
  }
}

function errorMessage(status: number, body: unknown): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join('; ')
    }
  }
  return `Request failed (${status})`
}

async function request<T>(method: string, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {}
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const response = await fetch(`/api${path}`, { method, credentials: 'include', headers, body: payload, ...init })
  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('content-type') ?? ''
  const data: unknown = contentType.includes('application/json') ? await response.json().catch(() => null) : null
  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}

export const api = {
  get: <T>(path: string, init?: RequestInit) => request<T>('GET', path, undefined, init),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}

/** Backwards-compatible helper used by early screens. */
export const apiGet = <T>(path: string, init?: RequestInit) => api.get<T>(path, init)

/** Upload that keeps the JSON body of 409/422 responses (duplicates, failed parses). */
export async function upload<T>(path: string, form: FormData): Promise<{ status: number; body: T }> {
  const response = await fetch(`/api${path}`, { method: 'POST', credentials: 'include', body: form })
  const body = (await response.json().catch(() => null)) as T
  if (!response.ok && ![409, 422].includes(response.status)) throw new ApiError(response.status, body)
  return { status: response.status, body }
}

export function qs(params: Record<string, string | number | boolean | null | undefined | string[]>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v))
    else search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
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
    return await api.get<Health>('/health')
  } catch (error) {
    if (error instanceof ApiError && error.status === 503 && error.body) return error.body as Health
    throw error
  }
}
