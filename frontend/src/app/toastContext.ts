import { createContext, useContext } from 'react'

export interface Toast {
  id: number
  title: string
  body?: string
  tone: 'alert' | 'info' | 'success' | 'error'
  to?: string
}

export interface ToastApi {
  push: (toast: Omit<Toast, 'id'>) => void
}

export const ToastContext = createContext<ToastApi>({ push: () => undefined })

export function useToast(): ToastApi {
  return useContext(ToastContext)
}
