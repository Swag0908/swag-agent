import { api } from './http'

export const getToday = () => api('/todo/today')
export const getTodos = (from, to) => {
  const q = new URLSearchParams({ from, to })
  return api(`/todo?${q}`)
}
export const createTodo = (payload) => api('/todo', { method: 'POST', body: payload })
export const updateTodo = (id, payload) => api(`/todo/${id}`, { method: 'PATCH', body: payload })
export const completeTodo = (id) => api(`/todo/${id}/complete`, { method: 'PATCH' })
export const deferTodo = (id, newDate) =>
  api(`/todo/${id}/defer`, { method: 'PATCH', body: { newDate } })
export const deleteTodo = (id) => api(`/todo/${id}`, { method: 'DELETE' })
export const getStats = (from, to) => {
  const q = new URLSearchParams()
  if (from) q.set('from', from)
  if (to) q.set('to', to)
  const s = q.toString()
  return api(`/todo/stats/daily${s ? '?' + s : ''}`)
}
