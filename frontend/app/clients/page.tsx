'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import AppShell from '@/components/app-shell'
import DataTable from '@/components/data-table'
import StatusBadge from '@/components/status-badge'
import { apiFetch, getAccessToken, handleAuthExpired } from '@/lib/api'

export default function ClientsPage() {
  const router = useRouter()
  const [rows, setRows] = useState<any[]>([])

  useEffect(() => {
    const token = getAccessToken()
    if (!token) return
    apiFetch<any[]>('/clients', token)
      .then(setRows)
      .catch((err) => {
        if (handleAuthExpired(err)) {
          router.replace('/')
        }
      })
  }, [router])

  return (
    <AppShell title="执行客户端" subtitle="客户端每 10 秒心跳；30 秒无心跳判定离线">
      <DataTable
        columns={['客户端ID', '账户', '版本', '状态', '能力', '最近心跳', '最近错误']}
        rows={rows.map((r) => [
          r.id,
          r.account_id,
          r.version,
          <StatusBadge key={r.id} value={r.status} />,
          (r.capabilities || []).join(','),
          new Date(r.last_heartbeat_at).toLocaleString(),
          r.last_error || '-'
        ])}
      />
    </AppShell>
  )
}
