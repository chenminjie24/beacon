'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect } from 'react'
import type { ReactNode } from 'react'

import { clearAuth, getAccessToken } from '@/lib/api'

const menus = [
  { href: '/dashboard', label: '仪表盘' },
  { href: '/signals', label: '信号' },
  { href: '/orders', label: '订单' },
  { href: '/risk', label: '风控' },
  { href: '/clients', label: '客户端' },
  { href: '/alerts', label: '告警' },
  { href: '/audit', label: '审计' }
]

export default function AppShell({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()

  useEffect(() => {
    if (!getAccessToken()) {
      router.replace('/')
    }
  }, [router])

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">QMT Gateway</div>
        <div className="brand-sub">Signal -&gt; Risk -&gt; Dispatch -&gt; QMT</div>
        <nav>
          {menus.map((item) => (
            <Link key={item.href} className={`nav-item ${pathname === item.href ? 'active' : ''}`} href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
        <button
          className="btn ghost"
          style={{ marginTop: 14 }}
          onClick={() => {
            clearAuth()
            router.replace('/')
          }}
        >
          退出登录
        </button>
      </aside>
      <main className="main">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-sub">{subtitle}</p>}
        {children}
      </main>
    </div>
  )
}
