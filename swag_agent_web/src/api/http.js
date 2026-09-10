// 统一 fetch 封装：自动携带 token、统一错误处理、401 跳登录。
import { authHeaders, clearAuth } from '../auth'

export async function api(path, { method = 'GET', body, headers = {}, timeoutMs = 0 } = {}) {
  const controller = timeoutMs > 0 ? new AbortController() : null
  const timeoutId = controller
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null

  try {
    const res = await fetch('/api' + path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
        ...headers
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller?.signal
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
        // Spring Boot 可能返回 message，也可能返回 Problem Details 的 detail 或默认 error。
        message = data?.message || data?.detail || data?.error || message
      } catch {
        /* ignore */
      }
      throw new Error(message)
    }

    if (res.status === 204) return null
    const text = await res.text()
    return text ? JSON.parse(text) : null
  } catch (e) {
    if (e?.name === 'AbortError') {
      throw new Error(`请求超时（${Math.ceil(timeoutMs / 1000)} 秒），请检查服务器与 GitHub 的网络连接`)
    }
    throw e
  } finally {
    if (timeoutId !== null) window.clearTimeout(timeoutId)
  }
}
