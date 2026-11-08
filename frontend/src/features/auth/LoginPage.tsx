import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

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
  const login = useMutation({
    mutationFn: () => api.post<User>('/auth/login', { email, password }),
    onSuccess: (user) => {
      queryClient.setQueryData(['me'], user)
      void navigate('/')
    },
  })

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
            <p className="mb-2 text-xs font-medium tracking-wide text-slate-500 uppercase">Demo users (password from .env)</p>
            <div className="grid grid-cols-2 gap-2">
              {demoUsers.data.map((u) => (
                <button
                  key={u.email}
                  type="button"
                  onClick={() => setEmail(u.email)}
                  className={`min-h-11 rounded-md border px-2 py-1 text-left text-xs hover:bg-slate-50 ${email === u.email ? 'border-slate-800' : 'border-slate-200'}`}
                >
                  <div className="font-medium">{ROLE_LABEL[u.role]}</div>
                  <div className="truncate text-slate-500">{u.email}</div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
