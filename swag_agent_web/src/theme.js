const KEY = 'swag-theme'

export function currentTheme() {
  return localStorage.getItem(KEY) || 'dark'
}

export function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem(KEY, theme)
}
