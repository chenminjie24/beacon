export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1'
const AUTH_NOTICE_KEY = 'auth_notice'
const AUTH_EXPIRED_NOTICE = '登录已过期，请重新登录'

export type LoginResp = {
  access_token: string
  refresh_token: string
  token_type: string
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiFetch<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {})
  headers.set('Content-Type', 'application/json')
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    cache: 'no-store'
  })

  if (!response.ok) {
    const msg = await response.text()
    throw new ApiError(msg || `HTTP ${response.status}`, response.status)
  }

  return response.json() as Promise<T>
}

export function handleAuthExpired(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 401) {
    return false
  }
  clearAuth()
  if (typeof window !== 'undefined') {
    sessionStorage.setItem(AUTH_NOTICE_KEY, AUTH_EXPIRED_NOTICE)
  }
  return true
}

export function popAuthNotice(): string {
  if (typeof window === 'undefined') return ''
  const notice = sessionStorage.getItem(AUTH_NOTICE_KEY) || ''
  if (notice) {
    sessionStorage.removeItem(AUTH_NOTICE_KEY)
  }
  return notice
}

export function getAccessToken(): string {
  if (typeof window === 'undefined') return ''
  return localStorage.getItem('access_token') || ''
}

export function clearAuth(): void {
  if (typeof window === 'undefined') return
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
}
