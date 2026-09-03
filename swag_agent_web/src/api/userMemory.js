import { api } from './http'

// ChatGPT Memory 式用户长期记忆管理
export const getUserMemory = () => api('/chat/user-memory')
export const setUserMemoryEnabled = (enabled) =>
  api('/chat/user-memory/settings', { method: 'PUT', body: { enabled } })
export const deleteUserMemory = (id) =>
  api(`/chat/user-memory/${id}`, { method: 'DELETE' })
