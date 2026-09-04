// 管理员端接口（后端仅 ADMIN 角色放行，前端只负责隐藏入口，权限以后端为准）。
import { api } from './http'

export const getRegisterSettings = () => api('/auth/admin/register-settings')
export const updateRegisterSettings = (payload) =>
  api('/auth/admin/register-settings', { method: 'PUT', body: payload })
export const regenerateRegisterCode = () =>
  api('/auth/admin/register-settings/regenerate', { method: 'POST' })
export const listUsers = () => api('/auth/admin/users')
export const setUserRole = (id, role) =>
  api(`/auth/admin/users/${id}/role`, { method: 'PUT', body: { role } })
