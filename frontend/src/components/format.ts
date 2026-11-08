/** Display helpers. All times are stored in UTC and shown in IST (Section 7.2). */

const IST = 'Asia/Kolkata'

export function formatIst(iso: string | null | undefined, withSeconds = false): string {
  if (!iso) return '-'
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: IST,
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: withSeconds ? '2-digit' : undefined,
    hour12: false,
  }).format(new Date(iso))
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  return new Intl.DateTimeFormat('en-IN', { timeZone: IST, day: '2-digit', month: 'short', year: 'numeric' }).format(
    new Date(iso),
  )
}

export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return ''
  const seconds = Math.round((now - new Date(iso).getTime()) / 1000)
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 36) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

export function num(value: string | number | null | undefined, decimals = 3): string {
  if (value === null || value === undefined || value === '') return '-'
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n.toFixed(decimals) : String(value)
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return value >= 10_000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`
}

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '-' : `${value.toFixed(1)}%`
}

export function hours(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return value < 48 ? `${value.toFixed(1)} h` : `${(value / 24).toFixed(1)} d`
}

export const ROLE_LABEL: Record<string, string> = {
  ADMIN: 'Admin',
  QUALITY_HEAD: 'Quality Head',
  SUPERVISOR: 'Shift Supervisor',
  PROCESS_OWNER: 'Process Owner',
  INSPECTOR: 'CMM Inspector',
  VIEWER: 'Viewer',
}

export const STATUS_LABEL: Record<string, string> = {
  OPEN: 'Open',
  ACKNOWLEDGED: 'Acknowledged',
  IN_PROGRESS: 'In progress',
  PENDING_VERIFICATION: 'Pending verification',
  CLOSED: 'Closed',
  CANCELLED: 'Cancelled',
}
