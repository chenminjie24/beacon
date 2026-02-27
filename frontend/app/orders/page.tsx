'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import AppShell from '@/components/app-shell'
import DataTable from '@/components/data-table'
import StatusBadge from '@/components/status-badge'
import { apiFetch, getAccessToken, handleAuthExpired } from '@/lib/api'

export default function OrdersPage() {
  const router = useRouter()
  const [rows, setRows] = useState<any[]>([])
  const [error, setError] = useState('')

  async function load() {
    const token = getAccessToken()
    if (!token) return
    try {
      const data = await apiFetch<any[]>('/orders?limit=200', token)
      setRows(data)
    } catch (err) {
      if (handleAuthExpired(err)) {
        router.replace('/')
        return
      }
      throw err
    }
  }

  async function cancelOrder(id: string) {
    try {
      const token = getAccessToken()
      if (!token) return
      await apiFetch(`/orders/${id}/cancel`, token, { method: 'POST' })
      await load()
    } catch (err) {
      if (handleAuthExpired(err)) {
        router.replace('/')
        return
      }
      setError(err instanceof Error ? err.message : '撤单失败')
    }
  }

  useEffect(() => {
    load().catch((err) => {
      setError(err instanceof Error ? err.message : '加载订单失败')
    })
  }, [router])

  return (
    <AppShell title="订单执行" subtitle="支持手工触发撤单（一期不支持改单）">
      {error && <div className="error">{error}</div>}
      <DataTable
        columns={['订单ID', '策略', '账户', '标的', '方向', '状态', '成交', '操作']}
        rows={rows.map((r) => [
          r.id,
          r.strategy_id,
          r.account_id,
          r.symbol,
          r.side,
          <StatusBadge key={r.id} value={r.status} />,
          `${r.filled_quantity} @ ${r.avg_price}`,
          <button className="btn" key={`${r.id}-op`} onClick={() => cancelOrder(r.id)}>
            撤单
          </button>
        ])}
      />
    </AppShell>
  )
}
