import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import { api } from '../../api/client'
import type { Role, User } from '../../api/types'
import { DemoDataBadge } from '../../components/DemoDataBadge'
import { ROLE_LABEL } from '../../components/format'
import { Button, ErrorBox, Field, inputClass } from '../../components/ui'

interface DemoUser {
  email: string
  full_name: string
  role: Role
}

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const demoUsers = useQuery({
    queryKey: ['demo-users'],
    queryFn: () => api.get<DemoUser[]>('/auth/demo-users'),
    retry: false,
  })
  const [params] = useSearchParams()
  const signedIn = (user: User) => {
    queryClient.clear()
    queryClient.setQueryData(['me'], user)
    void navigate(params.get('next') ?? '/')
  }
  const login = useMutation({
    mutationFn: () => api.post<User>('/auth/login', { email, password }),
    onSuccess: signedIn,
  })
  // Demo mode only: one click (or /login?as=owner.vmc02) signs in without typing a password.
  const demoLogin = useMutation({
    mutationFn: (demoEmail: string) => api.post<User>('/auth/demo-login', { email: demoEmail }),
    onSuccess: signedIn,
  })
  const autoTried = useRef(false)
  const asUser = params.get('as')
  useEffect(() => {
    if (!asUser || autoTried.current || !demoUsers.data?.length) return
    autoTried.current = true
    demoLogin.mutate(asUser.includes('@') ? asUser : `${asUser}@demo.local`)
  }, [asUser, demoUsers.data, demoLogin])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    login.mutate()
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-6 flex items-start justify-between gap-2">
          <div>
            <h1 className="text-xl font-semibold">Smart CMM Quality</h1>
            <p className="text-sm text-slate-600">Alert and action tracking</p>
          </div>
          <DemoDataBadge />
        </div>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Email">
            <input className={inputClass} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </Field>
          <Field label="Password">
            <input
              className={inputClass}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          <ErrorBox error={login.error} />
          <Button type="submit" className="w-full" disabled={login.isPending}>
            {login.isPending ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
        {demoUsers.data && demoUsers.data.length > 0 && (
          <div className="mt-6 border-t border-slate-200 pt-4">
            <p className="mb-2 text-xs font-medium tracking-wide text-slate-500 uppercase">Demo mode: one-click sign in</p>
            <ErrorBox error={demoLogin.error} />
            <div className="grid grid-cols-2 gap-2">
              {demoUsers.data.map((u) => (
                <button
                  key={u.email}
                  type="button"
                  onClick={() => demoLogin.mutate(u.email)}
                  disabled={demoLogin.isPending}
                  title={`Sign in as ${u.full_name} (demo mode only)`}
                  className="min-h-11 rounded-md border border-slate-200 px-2 py-1 text-left text-xs hover:border-slate-800 hover:bg-slate-50"
                >
                  <div className="font-medium">{ROLE_LABEL[u.role]}</div>
                  <div className="truncate text-slate-500">{u.email}</div>
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">Tip for recording: open /login?as=owner.vmc02 (or qhead, supervisor…) in each window.</p>
          </div>
        )}
      </div>
    </div>
  )
}
