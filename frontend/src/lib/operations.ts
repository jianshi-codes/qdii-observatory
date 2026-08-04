export function currentQuarterHistory(today = new Date()): {
  startDate: string
  previousQuarterEndDate: string
  lookbackDays: number
} {
  const baselineBufferDays = 7
  const year = today.getFullYear()
  const month = today.getMonth()
  const startMonth = Math.floor(month / 3) * 3
  const todayUtc = Date.UTC(year, month, today.getDate())
  const quarterStartUtc = Date.UTC(year, startMonth, 1)
  const previousQuarterEndUtc = quarterStartUtc - 86_400_000
  const startUtc = quarterStartUtc - baselineBufferDays * 86_400_000
  const startDate = new Date(startUtc).toISOString().slice(0, 10)
  return {
    startDate,
    previousQuarterEndDate: new Date(previousQuarterEndUtc).toISOString().slice(0, 10),
    lookbackDays: Math.max(1, Math.round((todayUtc - startUtc) / 86_400_000)),
  }
}
