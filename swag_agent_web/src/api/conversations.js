import { api } from './http'

// DeepSeek 式历史会话（多会话，各自独立上下文）
export const listConversations = () => api('/chat/conversations')
export const createConversation = (payload = {}) =>
  api('/chat/conversations', { method: 'POST', body: payload })
export const getConversationMessages = (id) => api(`/chat/conversations/${id}/messages`)
