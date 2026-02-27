'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import AppShell from '@/components/app-shell'
import { apiFetch, getAccessToken, handleAuthExpired } from '@/lib/api'

export default function DashboardPage() {
  const router = useRouter()
  const [metrics, setMetrics] = useState({
    today_signals: 0,
    success_orders: 0,
    failed_orders: 0,
    online_clients: 0,
    open_alerts: 0
  })

  useEffect(() => {
    const token = getAccessToken()
    if (!token) return
    apiFetch('/dashboard/metrics', token)
      .then((data) => setMetrics(data as typeof metrics))
      .catch((err) => {
        if (handleAuthExpired(err)) {
          router.replace('/')
        }
      })
  }, [router])

  const cards = [
    ['今日信号', metrics.today_signals],
    ['成功订单', metrics.success_orders],
    ['失败订单', metrics.failed_orders],
    ['在线客户端', metrics.online_clients],
    ['未关闭告警', metrics.open_alerts]
  ]

  return (
    <AppShell title="实盘仪表盘" subtitle="核心指标按秒级刷新时可改为轮询/WebSocket">
      <div className="grid metrics">
        {cards.map(([k, v]) => (
          <div className="card" key={k}>
            <div className="metric-label">{k}</div>
            <div className="metric-value">{v}</div>
          </div>
        ))}
      </div>
    </AppShell>
  )
}
