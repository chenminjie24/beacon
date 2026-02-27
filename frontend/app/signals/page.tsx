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

  useEffect(() => {
    const token = getAccessToken()
    if (!token) return
    apiFetch<any[]>('/signals?limit=200', token)
      .then(setRows)
      .catch((err) => {
        if (handleAuthExpired(err)) {
          router.replace('/')
        }
      })
  }, [router])

  return (
    <AppShell title="信号列表" subtitle="可用于排查幂等、风控拒绝与状态推进">
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
