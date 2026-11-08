import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { Link, Outlet } from 'react-router'

import { ToastContext, type Toast } from './toastContext'

const TONE = {
  alert: 'border-red-400 bg-red-50 text-red-900',
  info: 'border-slate-300 bg-white text-slate-900',
  success: 'border-green-400 bg-green-50 text-green-900',
  error: 'border-red-400 bg-white text-red-800',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = Date.now() + Math.random()
    setToasts((list) => [...list.slice(-3), { ...toast, id }])
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), toast.tone === 'alert' ? 12_000 : 5000)
  }, [])
  const value = useMemo(() => ({ push }), [push])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-96 max-w-[90vw] flex-col gap-2" aria-live="assertive">
        {toasts.map((t) => (
          <div key={t.id} role="status" className={`pointer-events-auto rounded-lg border-l-4 p-3 shadow-lg ${TONE[t.tone]}`}>
            <div className="text-sm font-semibold">{t.title}</div>
            {t.body && <div className="mt-1 text-xs whitespace-pre-line">{t.body}</div>}
            {t.to && (
              <Link to={t.to} className="mt-2 inline-block text-xs font-semibold underline">
                Open
              </Link>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

/** Root route element: toasts live inside the router so their links can navigate. */
export function ToastShell() {
  return (
    <ToastProvider>
      <Outlet />
    </ToastProvider>
  )
}
