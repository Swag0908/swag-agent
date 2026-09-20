import { api } from './http'

const enc = encodeURIComponent

export const getTree = () => api('/notes/tree')
export const getNote = (path) => api(`/notes/file?path=${enc(path)}`)
// 新建笔记：同名已存在时后端返回 409（不覆盖已有笔记）
export const createNote = (path, content) =>
  api('/notes/file', { method: 'POST', body: { path, content } })
// 保存（新建或覆盖）当前编辑的笔记
export const saveNote = (path, content) =>
  api('/notes/file', { method: 'PUT', body: { path, content } })

export const getNoteImportConfig = () => api('/notes/import/config')

export const importLocalNotes = (sourcePaths, targetDir) =>
  api('/notes/import/local', {
    method: 'POST',
    body: { sourcePaths, targetDir },
    timeoutMs: 120_000
  })

export const uploadNotes = (files, targetDir) => {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file, file.name)
    form.append('relativePaths', file.webkitRelativePath || file.name)
  }
  form.append('targetDir', targetDir)
  return api('/notes/import/upload', { method: 'POST', body: form, timeoutMs: 120_000 })
}

export const deleteNote = (path) => api(`/notes/file?path=${enc(path)}`, { method: 'DELETE' })
export const createDir = (path) => api('/notes/dir', { method: 'POST', body: { path } })
export const deleteFolder = (path, mode = 'trash') =>
  api(`/notes/dir?path=${enc(path)}&mode=${mode}`, { method: 'DELETE' })
export const renameEntry = (from, to) =>
  api('/notes/rename', { method: 'POST', body: { from, to } })

// 回收站
export const getTrash = () => api('/notes/trash')
export const restoreTrash = (id) => api(`/notes/trash/${enc(id)}/restore`, { method: 'POST' })
export const deleteTrashEntry = (id) => api(`/notes/trash/${enc(id)}`, { method: 'DELETE' })
export const clearTrashAll = () => api('/notes/trash', { method: 'DELETE' })
