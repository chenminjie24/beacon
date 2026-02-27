'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import AppShell from '@/components/app-shell'
import DataTable from '@/components/data-table'
import StatusBadge from '@/components/status-badge'
import { apiFetch, getAccessToken, handleAuthExpired } from '@/lib/api'

export default function AlertsPage() {
  const router = useRouter()
  const [rows, setRows] = useState<any[]>([])

  useEffect(() => {
    const token = getAccessToken()
    if (!token) return
    apiFetch<any[]>('/alerts?limit=200', token)
      .then(setRows)
      .catch((err) => {
        if (handleAuthExpired(err)) {
          router.replace('/')
        }
      })
  }, [router])

  return (
    <AppShell title="告警中心" subtitle="包含风控拒绝、下单失败、客户端离线等告警">
      <DataTable
        columns={['告警ID', '级别', '类别', '内容', '状态', '时间']}
        rows={rows.map((r) => [
          r.id,
          <StatusBadge key={r.id} value={r.level} />,
          r.category,
          r.message,
          <StatusBadge key={`${r.id}-status`} value={r.status} />,
          new Date(r.created_at).toLocaleString()
        ])}
      />
    </AppShell>
  )
}
