import {
  Activity,
  BarChart3,
  DatabaseZap,
  Menu,
  Orbit,
  Scale,
  WalletCards,
  X,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'

const portfolioEnabled = import.meta.env.VITE_QDII_ENABLE_PORTFOLIO === 'true'

const navigation = [
  { to: '/', label: '基金总览', icon: BarChart3, end: true },
  ...(portfolioEnabled ? [{ to: '/portfolio', label: '本地 Portfolio', icon: WalletCards }] : []),
  { to: '/compare', label: '基金对比', icon: Scale },
  { to: '/ops', label: '数据运维', icon: DatabaseZap },
]

export function AppShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink className="brand" to="/" aria-label="QDII 基金观察台首页">
          <span className="brand-mark"><Orbit size={21} strokeWidth={1.8} /></span>
          <span className="brand-copy">
            <strong>QDII Observatory</strong>
            <small>QDII 基金观察台</small>
          </span>
        </NavLink>

        <button
          className="menu-button"
          type="button"
          aria-label={menuOpen ? '关闭导航' : '打开导航'}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>

        <nav className={menuOpen ? 'main-nav is-open' : 'main-nav'} aria-label="主导航">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setMenuOpen(false)}
              className={({ isActive }) => isActive ? 'nav-link is-active' : 'nav-link'}
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="local-indicator" title="本地服务，不上传基金数据">
          <Activity size={14} />
          <span>本地模式</span>
        </div>
      </header>
      <main className="page-frame">{children}</main>
      <footer className="site-footer">
        <span>数据以来源报告与最新归档为准</span>
        <span>不构成投资建议</span>
      </footer>
    </div>
  )
}
