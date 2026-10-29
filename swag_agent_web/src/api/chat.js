// 流式调用后端聊天接口（经 Vite / nginx 代理转发到 Spring Boot）
//
// 后端有两种输出格式：
//   1. text/event-stream（本文件使用）：除了正文，还实时推送「思考中 / 正在调用哪个工具 /
//      工具跑完用了多久」。事件名为 ready / content / reasoning / tool_call / error / done。
//   2. text/plain：旧格式，只有正文，等价于把 content 事件拼起来（见 streamChatPlainText）。
import { authHeaders, clearAuth } from '../auth'

/** 一次聊天流的回调集合。 */
// onEvent(eventName, data) —— 每个 SSE 事件回调一次，data 是已解析好的 JSON 对象
// onDelta(text)         —— 正文增量（content 事件）的便捷回调，等价于 onEvent
export async function streamChat({ model, message, conversationId, signal, onDelta, onEvent }) {
  const params = new URLSearchParams()
  params.set('model', String(model))
  params.set('userInput', message)
  if (conversationId) params.set('conversationId', String(conversationId))
  const url = '/api/test/chat/stream/events?' + params.toString()

  // 显式带上会话 id：审计上下文按它把本次请求的事件挂到聊天会话上，
  // 删除会话时才能连审计记录一起回收（查询串里也有一份，防止代理改写请求头）。
  const conversationHeaders = conversationId
    ? { 'X-Conversation-Id': String(conversationId) }
    : {}

  const res = await fetch(url, {
    signal,
    headers: { Accept: 'text/event-stream', ...conversationHeaders, ...authHeaders() }
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
  // SSE 以「空行」分隔一条完整事件，跨 chunk 的半条事件先攒在 buffer 里
  let buffer = ''

  const handleBlock = (block) => {
    let eventName = 'message'
    const dataLines = []
    for (const line of block.split('\n')) {
      if (line.startsWith(':')) continue // 注释（心跳）
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
    }
    if (!dataLines.length) return

    let data = {}
    try {
      data = JSON.parse(dataLines.join('\n'))
      // Python 发送扁平对象；保留 Java 包装格式的兼容性，部署回滚后仍可流式聊天。
      data = data.data ?? data
    } catch {
      // 数据不是 JSON（理论上不会发生）：当作纯文本增量，别丢掉内容
      onDelta?.(dataLines.join('\n'))
      return
    }
    if (eventName === 'content' && typeof data.text === 'string') onDelta?.(data.text)
    onEvent?.(eventName, data)
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      if (block.trim()) handleBlock(block)
    }
  }
  // 冲刷解码器缓冲区与最后一条没有以空行结尾的事件
  buffer += decoder.decode()
  if (buffer.trim()) handleBlock(buffer)
}
