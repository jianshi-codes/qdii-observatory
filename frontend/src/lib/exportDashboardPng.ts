import { toPng } from 'html-to-image'

export interface DashboardExportOptions {
  filename: string
  width: number
  height: number
}

export async function exportDashboardPng(
  element: HTMLElement,
  { filename, width, height }: DashboardExportOptions,
): Promise<void> {
  await document.fonts?.ready
  element.classList.add('dashboard-export-mode')

  try {
    const availableHeight = height - 76
    const sourceHeight = Math.max(element.scrollHeight, availableHeight)
    const fit = Math.min(1, availableHeight / sourceHeight)
    const dataUrl = await toPng(element, {
      backgroundColor: '#f4f1e9',
      width,
      height,
      pixelRatio: 1,
      cacheBust: true,
      skipFonts: true,
      style: {
        boxSizing: 'border-box',
        width: `${width / fit}px`,
        maxWidth: 'none',
        height: `${height / fit}px`,
        margin: '0',
        padding: `${38 / fit}px`,
        background: '#f4f1e9',
        transform: fit < 1 ? `scale(${fit})` : 'none',
        transformOrigin: 'top left',
      },
    })
    const link = document.createElement('a')
    link.download = filename
    link.href = dataUrl
    link.click()
  } finally {
    element.classList.remove('dashboard-export-mode')
  }
}
