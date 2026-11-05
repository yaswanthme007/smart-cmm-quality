import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { createQueryClient } from './queryClient'
import { routes } from './routes'

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

function mockHealth(status: number, body: unknown) {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  )
}

describe('app shell', () => {
  it('shows the dashboard with the Demo data badge', async () => {
    mockHealth(200, { status: 'ok', db: 'ok', worker: 'not_configured', smtp: 'ok', demo_mode: true })
    renderAt('/')

    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByText('Demo data')).toBeInTheDocument()
    expect(await screen.findByText('Not configured')).toBeInTheDocument()
  })

  it('shows degraded health from a 503 body', async () => {
    mockHealth(503, { status: 'degraded', db: 'error', worker: 'not_configured', smtp: 'ok', demo_mode: true })
    renderAt('/')

    expect(await screen.findByText('Down')).toBeInTheDocument()
  })

  it('renders a not-found page for unknown routes', () => {
    mockHealth(200, {})
    renderAt('/does-not-exist')

    expect(screen.getByText('Page not found')).toBeInTheDocument()
  })
})
