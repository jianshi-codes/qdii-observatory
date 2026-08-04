export function currentQuarterHistory(today = new Date()): {
  startDate: string
  lookbackDays: number
} {
  const year = today.getFullYear()
  const month = today.getMonth()
  const startMonth = Math.floor(month / 3) * 3
  const startDate = `${year}-${String(startMonth + 1).padStart(2, '0')}-01`
  const todayUtc = Date.UTC(year, month, today.getDate())
  const startUtc = Date.UTC(year, startMonth, 1)
  return {
    startDate,
    lookbackDays: Math.max(1, Math.round((todayUtc - startUtc) / 86_400_000)),
  }
}
