'use client'

import { FormEvent, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import AppShell from '@/components/app-shell'
import { apiFetch, getAccessToken, handleAuthExpired } from '@/lib/api'

export default function RiskPage() {
  const router = useRouter()
  const [rule, setRule] = useState<any | null>(null)
  const [whitelistInput, setWhitelistInput] = useState('')
  const [blacklistInput, setBlacklistInput] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    const token = getAccessToken()
    if (!token) return
    apiFetch<any[]>('/risk-rules', token)
      .then((rows) => {
        const current = rows[0] || null
        setRule(current)
        if (current) {
          setWhitelistInput((current.whitelist || []).join(','))
          setBlacklistInput((current.blacklist || []).join(','))
        }
      })
      .catch((err) => {
        if (handleAuthExpired(err)) {
          router.replace('/')
        }
      })
  }, [router])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!rule) return
    const token = getAccessToken()
    if (!token) return
    try {
      await apiFetch(`/risk-rules/${rule.id}`, token, {
        method: 'PUT',
        body: JSON.stringify({
          ...rule,
          whitelist: whitelistInput
            .split(',')
            .map((x) => x.trim())
            .filter(Boolean),
          blacklist: blacklistInput
            .split(',')
            .map((x) => x.trim())
            .filter(Boolean)
        })
      })
      setMsg('已保存')
    } catch (err) {
      if (handleAuthExpired(err)) {
        router.replace('/')
        return
      }
      setMsg(err instanceof Error ? err.message : '保存失败')
    }
  }

  if (!rule) {
    return (
      <AppShell title="风控规则" subtitle="按 strategy_id + account_id 维度配置">
        <div className="card">暂无风控规则</div>
      </AppShell>
    )
  }

  return (
    <AppShell title="风控规则" subtitle="执行顺序：时段 -> 黑白名单 -> 最小单位/金额 -> 单笔 -> 日累计">
      <form className="card grid" onSubmit={onSubmit}>
        <div className="row">
          <label style={{ minWidth: 120 }}>单笔金额上限</label>
          <input
            className="input"
            value={rule.max_single_amount}
            onChange={(e) => setRule({ ...rule, max_single_amount: Number(e.target.value) })}
          />
        </div>
        <div className="row">
          <label style={{ minWidth: 120 }}>单笔数量上限</label>
          <input
            className="input"
            value={rule.max_single_quantity}
            onChange={(e) => setRule({ ...rule, max_single_quantity: Number(e.target.value) })}
          />
        </div>
        <div className="row">
          <label style={{ minWidth: 120 }}>日累计金额上限</label>
          <input
            className="input"
            value={rule.daily_max_amount}
            onChange={(e) => setRule({ ...rule, daily_max_amount: Number(e.target.value) })}
          />
        </div>
        <div className="row">
          <label style={{ minWidth: 120 }}>最小下单金额</label>
          <input
            className="input"
            value={rule.min_order_amount}
            onChange={(e) => setRule({ ...rule, min_order_amount: Number(e.target.value) })}
          />
        </div>
        <div className="row">
          <label style={{ minWidth: 120 }}>最小手数</label>
          <input
            className="input"
            value={rule.min_lot_size}
            onChange={(e) => setRule({ ...rule, min_lot_size: Number(e.target.value) })}
          />
        </div>
        <div className="row">
          <label style={{ minWidth: 120 }}>白名单(逗号)</label>
          <input className="input" value={whitelistInput} onChange={(e) => setWhitelistInput(e.target.value)} />
        </div>
        <div className="row">
          <label style={{ minWidth: 120 }}>黑名单(逗号)</label>
          <input className="input" value={blacklistInput} onChange={(e) => setBlacklistInput(e.target.value)} />
        </div>
        <div className="row">
          <button className="btn primary">保存规则</button>
          {msg && <span className="badge ok">{msg}</span>}
        </div>
      </form>
    </AppShell>
  )
}
