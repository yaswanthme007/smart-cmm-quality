import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { createQueryClient } from './queryClient'
import { routes } from './routes'

type Handler = (url: string) => [number, unknown]

function mockApi(handler: Handler) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input)
    const [status, body] = handler(url)
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  })
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const SUMMARY = {
  k1: { inspected: 10, ok: 8, ok_only: 7, marginal: 1, nok: 2 },
  k2: { ok_pct: 80, nok_pct: 20, marginal_pct: 10, characteristics_measured: 50, characteristics_nok: 2, characteristic_nok_pct: 4 },
  k3: { count: 2, median_ms: 120, p95_ms: 240, max_ms: 250, email_count: 0, email_median_ms: null, email_p95_ms: null },
  k3b: { count: 10, median_s: 140, p95_s: 230 },
  k4: { open: 2, pending: 0, closed: 0, cancelled: 0, overdue: 0, escalated_open: 1 },
  k5: { closed_count: 0, median_h: null, p90_h: null, closed_on_time_pct: null, ack_median_min: null },
  ageing: [{ bucket: '0-1 d', count: 2 }],
  generated_at: '2026-11-08T00:00:00Z',
}

const QHEAD = { id: 'u1', email: 'qhead@demo.local', full_name: 'Quality Head (demo)', role: 'QUALITY_HEAD', department_id: null }

describe('app', () => {
  it('sends a logged-out user to the login page with the demo user picker', async () => {
    mockApi((url) => {
      if (url.includes('/auth/me')) return [401, { detail: 'Not logged in' }]
      if (url.includes('/auth/demo-users')) return [200, [{ email: 'qhead@demo.local', full_name: 'Q', role: 'QUALITY_HEAD' }]]
      return [404, {}]
    })
    const router = renderAt('/')
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
    expect(await screen.findByText('qhead@demo.local')).toBeInTheDocument()
    expect(screen.getByText('Demo data')).toBeInTheDocument()
  })

  it('shows the KPI tiles for a logged-in user', async () => {
    mockApi((url) => {
      if (url.includes('/auth/me')) return [200, QHEAD]
      if (url.includes('/kpi/summary')) return [200, SUMMARY]
      if (url.includes('/alerts')) return [200, { total: 0, unread: 0, items: [] }]
      return [200, []]
    })
    renderAt('/')
    expect(await screen.findByRole('heading', { name: 'Quality dashboard' })).toBeInTheDocument()
    expect(await screen.findByText('80.0%')).toBeInTheDocument()
    expect(screen.getByText('incl. 1 marginal')).toBeInTheDocument()
    expect(screen.getByText('120 ms')).toBeInTheDocument()
    expect(screen.getByText('Audit log')).toBeInTheDocument() // role-aware navigation
  })

  it('hides admin navigation from a process owner', async () => {
    mockApi((url) => {
      if (url.includes('/auth/me')) return [200, { ...QHEAD, role: 'PROCESS_OWNER' }]
      if (url.includes('/kpi/summary')) return [200, SUMMARY]
      if (url.includes('/alerts')) return [200, { total: 0, unread: 0, items: [] }]
      return [200, []]
    })
    renderAt('/')
    expect(await screen.findByRole('heading', { name: 'Quality dashboard' })).toBeInTheDocument()
    expect(screen.queryByText('Audit log')).not.toBeInTheDocument()
    expect(screen.queryByText('Settings')).not.toBeInTheDocument()
  })

  it('signs a demo user in with one click, without a password', async () => {
    let loggedIn = false
    mockApi((url) => {
      if (url.includes('/auth/demo-login')) {
        loggedIn = true
        return [200, { ...QHEAD, role: 'PROCESS_OWNER', email: 'owner.vmc02@demo.local' }]
      }
      if (url.includes('/auth/me')) return loggedIn ? [200, { ...QHEAD, role: 'PROCESS_OWNER' }] : [401, {}]
      if (url.includes('/auth/demo-users')) return [200, [{ email: 'owner.vmc02@demo.local', full_name: 'Owner', role: 'PROCESS_OWNER' }]]
      if (url.includes('/kpi/summary')) return [200, SUMMARY]
      if (url.includes('/alerts')) return [200, { total: 0, unread: 0, items: [] }]
      return [200, []]
    })
    const router = renderAt('/login')
    fireEvent.click(await screen.findByText('owner.vmc02@demo.local'))
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
    const call = vi.mocked(fetch).mock.calls.find(([u]) => String(u).includes('/auth/demo-login'))
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ email: 'owner.vmc02@demo.local' })
  })

  it('renders a not-found page for unknown routes', async () => {
    mockApi((url) => (url.includes('/auth/me') ? [200, QHEAD] : [200, { total: 0, unread: 0, items: [] }]))
    renderAt('/does-not-exist')
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
  })
})
