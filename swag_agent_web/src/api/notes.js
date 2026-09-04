import { api } from './http'

const enc = encodeURIComponent

export const getTree = () => api('/notes/tree')
export const getNote = (path) => api(`/notes/file?path=${enc(path)}`)
export const saveNote = (path, content) =>
  api('/notes/file', { method: 'PUT', body: { path, content } })
export const deleteNote = (path) => api(`/notes/file?path=${enc(path)}`, { method: 'DELETE' })
export const createDir = (path) => api('/notes/dir', { method: 'POST', body: { path } })
export const deleteDir = (path) => api(`/notes/dir?path=${enc(path)}`, { method: 'DELETE' })
export const renameEntry = (from, to) =>
  api('/notes/rename', { method: 'POST', body: { from, to } })
