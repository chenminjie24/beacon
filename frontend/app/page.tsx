'use client'

import { FormEvent, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import { API_BASE, LoginResp, popAuthNotice } from '@/lib/api'

export default function LoginPage() {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123456')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const router = useRouter()

  useEffect(() => {
    const notice = popAuthNotice()
    if (notice) {
      setError(notice)
    }
  }, [])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const resp = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      })
      if (!resp.ok) {
        throw new Error(await resp.text())
      }
      const data = (await resp.json()) as LoginResp
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      router.replace('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit}>
        <h1 className="page-title" style={{ marginBottom: 8 }}>
          QMT 实盘中台
        </h1>
        <p className="page-sub">一期管理后台登录</p>
        <div className="grid" style={{ gap: 10 }}>
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="用户名" />
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="密码"
          />
          <button className="btn primary" disabled={loading}>
            {loading ? '登录中...' : '登录'}
          </button>
          {error && <div className="error">{error}</div>}
        </div>
      </form>
    </div>
  )
}
