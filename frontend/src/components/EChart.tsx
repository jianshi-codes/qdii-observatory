import { BarChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import type { EChartsOption } from 'echarts'
import { SVGRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

echarts.use([
  BarChart,
  LineChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  SVGRenderer,
])

export function EChart({ option, height = 320, ariaLabel }: {
  option: EChartsOption
  height?: number
  ariaLabel: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = echarts.init(container, undefined, { renderer: 'svg' })
    chart.setOption(option)
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [option])

  return <div ref={containerRef} className="chart" style={{ height }} role="img" aria-label={ariaLabel} />
}
