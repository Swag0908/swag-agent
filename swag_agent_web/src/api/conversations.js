import { api } from './http'

// DeepSeek 式历史会话（多会话，各自独立上下文）
export const listConversations = () => api('/chat/conversations')
export const createConversation = (payload = {}) =>
  api('/chat/conversations', { method: 'POST', body: payload })
export const getConversationMessages = (id) => api(`/chat/conversations/${id}/messages`)

// 删除会话：后端会把聊天记录、短期/向量记忆、该会话的审计记录一起永久删除
export const deleteConversation = (id) =>
  api(`/chat/conversations/${id}`, { method: 'DELETE' })

// 清空全部历史会话，返回 { deleted }
export const clearConversations = () => api('/chat/conversations', { method: 'DELETE' })

// 收藏 / 取消收藏，并可附带备注名（只影响列表展示，不改会话原标题）
export const setConversationFavorite = (id, favorite, note) =>
  api(`/chat/conversations/${id}/favorite`, { method: 'PUT', body: { favorite, note } })

// 收藏区拖拽排序：按提交的完整 id 顺序重排，返回刷新后的会话列表
export const reorderFavoriteConversations = (ids) =>
  api('/chat/conversations/favorites/order', { method: 'PUT', body: { ids } })

// 删除会话内的一条对话；后端会把与它配对的那条一起删掉并重建记忆，返回剩余消息
export const deleteConversationMessage = (conversationId, messageId) =>
  api(`/chat/conversations/${conversationId}/messages/${messageId}`, { method: 'DELETE' })
