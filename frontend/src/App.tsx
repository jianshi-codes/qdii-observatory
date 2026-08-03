import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { LoadingPanel } from './components/StatePanel'
import { FundOverviewPage } from './pages/FundOverviewPage'

const ComparePage = lazy(() => import('./pages/ComparePage').then((module) => ({ default: module.ComparePage })))
const DataOpsPage = lazy(() => import('./pages/DataOpsPage').then((module) => ({ default: module.DataOpsPage })))
const FundDetailPage = lazy(() => import('./pages/FundDetailPage').then((module) => ({ default: module.FundDetailPage })))
const PortfolioPage = lazy(() => import('./pages/PortfolioPage').then((module) => ({ default: module.PortfolioPage })))

export function App() {
  return (
    <AppShell>
      <Suspense fallback={<LoadingPanel label="正在载入观察台页面…" />}>
        <Routes>
          <Route path="/" element={<FundOverviewPage />} />
          <Route path="/funds/:fundId" element={<FundDetailPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/ops" element={<DataOpsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppShell>
  )
}
