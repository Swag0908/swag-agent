// 流式调用后端聊天接口（经 Vite 代理转发到 Spring Boot）
// 后端返回 text/plain 的纯文本流，逐块回调。
import { authHeaders, clearAuth } from '../auth'

export async function streamChat({ model, message, signal, onDelta }) {
  const url =
    '/api/test/chat/stream?model=' +
    encodeURIComponent(model) +
    '&userInput=' +
    encodeURIComponent(message)

  const res = await fetch(url, {
    signal,
    headers: { Accept: 'text/plain', ...authHeaders() }
  })

  if (res.status === 401) {
    clearAuth()
    if (location.pathname !== '/login') location.href = '/login'
    throw new Error('未登录或登录已过期')
  }

  if (!res.ok) {
    let detail = ''
    try {
      detail = await res.text()
    } catch {
      /* ignore */
    }
    throw new Error(`请求失败 (HTTP ${res.status})${detail ? '：' + detail : ''}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    onDelta(decoder.decode(value, { stream: true }))
  }
  // 冲刷解码器缓冲区中可能残留的多字节字符
  const tail = decoder.decode()
  if (tail) onDelta(tail)
}
