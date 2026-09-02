import { api } from './http'

export function getBookmarks({ folderId, q, unclassified = false } = {}) {
  const params = new URLSearchParams()
  if (folderId != null) params.set('folderId', folderId)
  if (q) params.set('q', q)
  if (unclassified) params.set('unclassified', 'true')
  const query = params.toString()
  return api(`/bookmarks${query ? '?' + query : ''}`)
}

export function createFolder(payload) {
  return api('/bookmarks/folders', { method: 'POST', body: payload })
}

export function updateFolder(id, payload) {
  return api(`/bookmarks/folders/${id}`, { method: 'PATCH', body: payload })
}

export function deleteFolder(id, cascade = false) {
  return api(`/bookmarks/folders/${id}?cascade=${cascade}`, { method: 'DELETE' })
}

export function createBookmark(payload) {
  return api('/bookmarks', { method: 'POST', body: payload })
}

export function updateBookmark(id, payload) {
  return api(`/bookmarks/${id}`, { method: 'PATCH', body: payload })
}

export function deleteBookmark(id) {
  return api(`/bookmarks/${id}`, { method: 'DELETE' })
}
