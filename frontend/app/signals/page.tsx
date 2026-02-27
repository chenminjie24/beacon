'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import AppShell from '@/components/app-shell'
import DataTable from '@/components/data-table'
import StatusBadge from '@/components/status-badge'
import { apiFetch, getAccessToken, handleAuthExpired } from '@/lib/api'

export default function SignalsPage() {
  const router = useRouter()
  const [rows, setRows] = useState<any[]>([])
  const [error, setError] = useState('')

  async function load() {
    const token = getAccessToken()
    if (!token) return
    try {
      const data = await apiFetch<any[]>('/signals?limit=200', token)
      setRows(data)
    } catch (err) {
      if (handleAuthExpired(err)) {
        router.replace('/')
        return
      }
      throw err
    }
  }

  useEffect(() => {
    load().catch((err) => {
      setError(err instanceof Error ? err.message : '加载信号失败')
    })
  }, [router])

  return (
    <AppShell title="信号列表" subtitle="可用于排查幂等、风控拒绝与状态推进">
      {error && <div className="error">{error}</div>}
      <DataTable
        columns={['ID', '平台', '策略', '账户', '标的', '方向', '状态', '时间']}
        rows={rows.map((r) => [
          r.id,
          r.source_platform,
          r.strategy_id,
          r.account_id,
          r.symbol,
          r.side,
          <StatusBadge key={r.id} value={r.status} />,
          new Date(r.created_at).toLocaleString()
        ])}
      />
    </AppShell>
  )
}
