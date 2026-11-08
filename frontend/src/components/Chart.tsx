import { BarChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { useEffect, useRef } from 'react'

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  MarkPointComponent,
  DataZoomComponent,
  CanvasRenderer,
])

/** Thin Apache ECharts wrapper (Section 6 D10). `onClick` receives the clicked data index. */
export function Chart({
  option,
  height = 260,
  onClick,
}: {
  option: EChartsCoreOption
  height?: number
  onClick?: (params: { dataIndex: number; name: string; seriesName?: string }) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current || typeof window === 'undefined' || !('ResizeObserver' in window)) return
    const chart = echarts.init(ref.current)
    chartRef.current = chart
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(ref.current)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption(option, true)
  }, [option])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !onClick) return
    const handler = (p: unknown) => onClick(p as { dataIndex: number; name: string; seriesName?: string })
    chart.on('click', handler)
    return () => {
      if (!chart.isDisposed()) chart.off('click', handler)
    }
  }, [onClick])

  return <div ref={ref} style={{ height }} className="w-full" />
}
