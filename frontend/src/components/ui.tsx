/* Shared UI primitives (shadcn-style, Tailwind). Result colours always come with a text label. */
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router'

import type { NcStatus, Result, Severity } from '../api/types'
import { cn } from './cn'
import { STATUS_LABEL } from './format'


const RESULT_STYLE: Record<Result, string> = {
  OK: 'bg-green-100 text-green-800 border-green-300',
  MARGINAL: 'bg-amber-100 text-amber-900 border-amber-300',
  NOK: 'bg-red-100 text-red-800 border-red-300',
}
const RESULT_TEXT: Record<Result, string> = { OK: 'OK', MARGINAL: 'Marginal', NOK: 'Not OK' }
const RESULT_ICON: Record<Result, string> = { OK: '✓', MARGINAL: '!', NOK: '✕' }

export function ResultChip({ result, suspect }: { result: Result | null | undefined; suspect?: boolean }) {
  if (!result) return <span className="text-slate-400">-</span>
  return (
    <span
      className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold', RESULT_STYLE[result])}
      title={suspect ? 'Suspect value: possible probing/entry error, re-measure' : undefined}
    >
      <span aria-hidden>{RESULT_ICON[result]}</span>
      {RESULT_TEXT[result]}
      {suspect && <span className="ml-1 rounded bg-white/70 px-1 text-[10px]">suspect</span>}
    </span>
  )
}

const STATUS_STYLE: Record<NcStatus, string> = {
  OPEN: 'bg-red-50 text-red-800 border-red-200',
  ACKNOWLEDGED: 'bg-orange-50 text-orange-800 border-orange-200',
  IN_PROGRESS: 'bg-blue-50 text-blue-800 border-blue-200',
  PENDING_VERIFICATION: 'bg-violet-50 text-violet-800 border-violet-200',
  CLOSED: 'bg-green-50 text-green-800 border-green-200',
  CANCELLED: 'bg-slate-100 text-slate-600 border-slate-200',
}

export function StatusChip({ status }: { status: NcStatus }) {
  return (
    <span className={cn('inline-block rounded-full border px-2 py-0.5 text-xs font-medium', STATUS_STYLE[status])}>
      {STATUS_LABEL[status]}
    </span>
  )
}

const SEVERITY_STYLE: Record<Severity, string> = {
  CRITICAL: 'bg-red-700 text-white',
  SIGNIFICANT: 'bg-amber-500 text-white',
  STANDARD: 'bg-slate-500 text-white',
}

export function SeverityChip({ severity }: { severity: Severity | null | undefined }) {
  if (!severity) return null
  return (
    <span className={cn('inline-block rounded px-1.5 py-0.5 text-[11px] font-semibold tracking-wide', SEVERITY_STYLE[severity])}>
      {severity}
    </span>
  )
}

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
const VARIANT: Record<Variant, string> = {
  primary: 'bg-slate-900 text-white hover:bg-slate-700 disabled:bg-slate-400',
  secondary: 'border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:text-slate-400',
  danger: 'bg-red-700 text-white hover:bg-red-600 disabled:bg-red-300',
  ghost: 'text-slate-700 hover:bg-slate-100',
}

export function Button({
  variant = 'primary',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed',
        VARIANT[variant],
        className,
      )}
      {...props}
    />
  )
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-lg border border-slate-200 bg-white p-4 shadow-sm', className)}>
      {(title || actions) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-slate-700">{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  )
}

export function StatTile({
  label,
  value,
  sub,
  to,
  tone = 'default',
  hint,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  to?: string
  tone?: 'default' | 'ok' | 'nok' | 'warn'
  hint?: string
}) {
  const toneClass = { default: 'text-slate-900', ok: 'text-green-700', nok: 'text-red-700', warn: 'text-amber-700' }[tone]
  const body = (
    <div className="h-full rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-400" title={hint}>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={cn('mt-1 text-3xl font-semibold tabular-nums', toneClass)}>{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  )
  return to ? (
    <Link to={to} className="block h-full">
      {body}
    </Link>
  ) : (
    body
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'w-full min-h-10 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-600 focus:outline-none focus:ring-2 focus:ring-slate-200'

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-8 text-center text-sm text-slate-500">{children}</div>
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {error instanceof Error ? error.message : String(error)}
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-600">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

/** Horizontal bar: where the actual value sits between LSL and USL (green zone = tolerance). */
export function LimitBar({
  actual,
  lsl,
  usl,
  result,
}: {
  actual: number
  lsl: number | null
  usl: number | null
  result: Result
}) {
  const lo = lsl ?? 0
  const hi = usl ?? lo
  const width = hi - lo || Math.abs(hi) || 1
  const min = lo - width * 0.5
  const max = hi + width * 0.5
  const pos = (x: number) => Math.min(100, Math.max(0, ((x - min) / (max - min)) * 100))
  const marker = { OK: 'bg-green-700', MARGINAL: 'bg-amber-600', NOK: 'bg-red-700' }[result]
  return (
    <div className="relative h-3 w-40 rounded bg-red-100" aria-label={`actual ${actual} between ${lsl ?? '-'} and ${usl ?? '-'}`}>
      <div className="absolute inset-y-0 bg-green-200" style={{ left: `${pos(lo)}%`, width: `${pos(hi) - pos(lo)}%` }} />
      <div className={cn('absolute -top-0.5 h-4 w-1 rounded', marker)} style={{ left: `calc(${pos(actual)}% - 2px)` }} />
    </div>
  )
}
