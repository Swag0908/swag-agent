// 统一 fetch 封装：自动携带 token、统一错误处理、401 跳登录。
import { authHeaders, clearAuth } from '../auth'

export async function api(path, { method = 'GET', body, headers = {} } = {}) {
  const res = await fetch('/api' + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...headers
    },
    body: body === undefined ? undefined : JSON.stringify(body)
  })

  if (res.status === 401) {
    clearAuth()
    if (location.pathname !== '/login') location.href = '/login'
    throw new Error('未登录或登录已过期')
  }

  if (!res.ok) {
    let message = `请求失败 (HTTP ${res.status})`
    try {
      const data = await res.json()
      if (data?.message) message = data.message
    } catch {
      /* ignore */
    }
    throw new Error(message)
  }

  if (res.status === 204) return null
  const text = await res.text()
  return text ? JSON.parse(text) : null
}
