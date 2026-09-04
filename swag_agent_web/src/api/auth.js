import { api } from './http'

export const register = (payload) => api('/auth/register', { method: 'POST', body: payload })
export const login = (payload) => api('/auth/login', { method: 'POST', body: payload })
export const logout = () => api('/auth/logout', { method: 'POST' })
export const me = () => api('/auth/me')
