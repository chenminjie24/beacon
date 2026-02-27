'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import AppShell from '@/components/app-shell'
import DataTable from '@/components/data-table'
import { apiFetch, getAccessToken, handleAuthExpired } from '@/lib/api'

export default function AuditPage() {
  const router = useRouter()
  const [rows, setRows] = useState<any[]>([])

  useEffect(() => {
    const token = getAccessToken()
    if (!token) return
    apiFetch<any[]>('/audit-logs?limit=300', token)
      .then(setRows)
      .catch((err) => {
        if (handleAuthExpired(err)) {
          router.replace('/')
        }
      })
  }, [router])

  return (
    <AppShell title="审计日志" subtitle="关键动作全量可追溯（登录、改风控、手工撤单等）">
      <DataTable
        columns={['ID', '执行者', '动作', '资源', '详情', '时间']}
        rows={rows.map((r) => [
          r.id,
          r.actor,
          r.action,
          `${r.resource_type}/${r.resource_id}`,
          JSON.stringify(r.detail),
          new Date(r.created_at).toLocaleString()
        ])}
      />
    </AppShell>
  )
}
