// 登录态存储：令牌 + 用户信息。
const TOKEN_KEY = 'swag-token'
const USER_KEY = 'swag-user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setAuth({ token, userId, username, displayName, role }) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify({ userId, username, displayName, role }))
}

export function setUser(patch) {
  const current = getUser()
  localStorage.setItem(USER_KEY, JSON.stringify({ ...current, ...patch }))
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function isAuthed() {
  return !!getToken()
}

export function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}
