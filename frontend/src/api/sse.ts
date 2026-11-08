import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

export interface LiveEvent {
  type: 'alert.created' | 'nc.updated' | 'report.ingested' | 'spc.signal' | 'kpi.invalidated'
  id?: string
  kind?: string
  title?: string
  nc_id?: string
  recipient_user_id?: string
}

const EVENT_TYPES: LiveEvent['type'][] = ['alert.created', 'nc.updated', 'report.ingested', 'spc.signal', 'kpi.invalidated']

/** Query keys refreshed on each live event (TanStack Query invalidation keeps every screen live). */
const INVALIDATES: Record<LiveEvent['type'], string[][]> = {
  'alert.created': [['alerts']],
  'nc.updated': [['ncs'], ['nc'], ['timeline']],
  'report.ingested': [['reports'], ['spc']],
  'spc.signal': [['spc']],
  'kpi.invalidated': [['kpi']],
}

/** Opens one EventSource on /api/stream (cookie auth) and invalidates cached queries. */
export function useLiveEvents(enabled: boolean, onAlert?: (event: LiveEvent) => void): boolean {
  const queryClient = useQueryClient()
  const [connected, setConnected] = useState(false)
  const onAlertRef = useRef(onAlert)
  useEffect(() => {
    onAlertRef.current = onAlert
  }, [onAlert])

  useEffect(() => {
    if (!enabled || typeof EventSource === 'undefined') return
    const source = new EventSource('/api/stream', { withCredentials: true })
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    const handlers = EVENT_TYPES.map((type) => {
      const handler = (message: MessageEvent<string>) => {
        let event: LiveEvent
        try {
          event = JSON.parse(message.data) as LiveEvent
        } catch {
          return
        }
        for (const key of INVALIDATES[type]) void queryClient.invalidateQueries({ queryKey: key })
        if (type === 'alert.created') onAlertRef.current?.(event)
      }
      source.addEventListener(type, handler as EventListener)
      return [type, handler] as const
    })
    return () => {
      handlers.forEach(([type, handler]) => source.removeEventListener(type, handler as EventListener))
      source.close()
      setConnected(false)
    }
  }, [enabled, queryClient])

  return connected
}
