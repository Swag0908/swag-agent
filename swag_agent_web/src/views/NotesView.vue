<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  getTree,
  getNote,
  saveNote,
  deleteNote,
  createDir,
  deleteFolder,
  renameEntry,
  getTrash,
  restoreTrash,
  deleteTrashEntry,
  clearTrashAll
} from '../api/notes'
import { getUser, clearAuth } from '../auth'
import { currentTheme, applyTheme } from '../theme'
import { logout as logoutApi } from '../api/auth'

const router = useRouter()
const user = getUser()

// 默认「未分类」文件夹（根目录散笔记 / 恢复兜底 / 删文件夹平铺都会用到它）
const UNCLASSIFIED = '未分类'

const theme = ref(currentTheme())
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  applyTheme(theme.value)
}

// ---------------- 目录树 ----------------
const tree = ref({ name: '', path: '', type: 'dir', children: [] })
const loadingTree = ref(false)
const filter = ref('')
const openPaths = ref(new Set())
const treeError = ref('')
// 当前“新建文件/文件夹”的目标目录：选中且展开的文件夹；收起/未选时为上级或根
const selectedDir = ref('')
// 目录树只允许一个高亮项，与当前仍在编辑器中打开的笔记分开管理
const selectedPath = ref('')

// ---------------- 回收站 ----------------
const trashOpen = ref(false)
const trashItems = ref([])
const trashLoading = ref(false)
const trashError = ref('')
const trashCount = computed(() => trashItems.value.length)

function joinPath(dir, name) {
  return dir ? dir + '/' + name : name
}
function parentOf(path) {
  const idx = path.lastIndexOf('/')
  return idx < 0 ? '' : path.slice(0, idx)
}
function baseName(path) {
  const idx = path.lastIndexOf('/')
  return idx < 0 ? path : path.slice(idx + 1)
}

function isDir(node) {
  return node?.type === 'dir'
}

function collectDirPaths(node, acc) {
  if (!node || !isDir(node)) return acc
  acc.add(node.path)
  for (const child of node.children || []) collectDirPaths(child, acc)
  return acc
}

async function loadTree({ keepOpen = true } = {}) {
  loadingTree.value = true
  treeError.value = ''
  try {
    tree.value = await getTree()
    if (!keepOpen) {
      openPaths.value = new Set(collectDirPaths(tree.value, new Set()))
    } else {
      const next = new Set(openPaths.value)
      for (const p of collectDirPaths(tree.value, new Set())) next.add(p)
      openPaths.value = next
    }
  } catch (e) {
    treeError.value = e?.message || '加载笔记目录失败'
  } finally {
    loadingTree.value = false
  }
}

function toggleOpen(path) {
  const next = new Set(openPaths.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  openPaths.value = next
}

// 文件夹/笔记行点击：文件夹=选中（高亮）+开合；文件=打开笔记
function onRowClick(row) {
  selectedPath.value = row.path
  if (row.dir) {
    toggleOpen(row.path)
    selectedDir.value = row.path
  } else {
    selectedDir.value = parentOf(row.path)
    openNote(row.path)
  }
}

// 新建目标目录：选中的文件夹处于展开态 → 建在它内部；收起态 → 建在它父级
function folderContext() {
  const sel = selectedDir.value
  if (!sel) return ''
  return openPaths.value.has(sel) ? sel : parentOf(sel)
}

// 新建目标：文件默认落「未分类」（未选中文件夹时），文件夹新建则落选中文件夹/根
function noteParent() {
  return folderContext() || UNCLASSIFIED
}
function dirParent() {
  return folderContext()
}

// 顶层「未分类」是系统文件夹：不可删除/改名/拖走
function isSystemFolder(row) {
  return !!(row && row.dir && row.name === UNCLASSIFIED && parentOf(row.path) === '')
}

// 选中项被删除后清理高亮，并把新建目标回退到它的父级
function fixSelectionAfterRemove(removedPath) {
  if (selectedPath.value === removedPath || selectedPath.value?.startsWith(removedPath + '/')) {
    selectedPath.value = ''
  }
  if (selectedDir.value === removedPath || selectedDir.value?.startsWith(removedPath + '/')) {
    selectedDir.value = parentOf(removedPath)
  }
}

// ---------------- 移动（重命名/拖拽共用） ----------------
async function moveEntry(from, to, isDir) {
  // 若移动的是当前正在编辑的笔记（或其所在文件夹），先落盘再移动，避免丢内容
  const affected =
    currentPath.value === from ||
    (isDir && !!currentPath.value && currentPath.value.startsWith(from + '/'))
  if (affected) await flushSave()
  await renameEntry(from, to)

  const movedSelection = selectedPath.value === from || (isDir && selectedPath.value.startsWith(from + '/'))
  if (movedSelection) selectedPath.value = to + selectedPath.value.slice(from.length)
  const movedContext = selectedDir.value === from || (isDir && selectedDir.value.startsWith(from + '/'))
  if (movedContext) selectedDir.value = to + selectedDir.value.slice(from.length)

  await loadTree()
  if (affected) {
    const old = currentPath.value
    if (old === from) await openNote(to)
    else await openNote(to + old.slice(from.length))
  } else {
    ensureVisible(to)
  }
}

// ---------------- 拖拽移动（笔记/文件夹 → 文件夹/根目录） ----------------
const dragSource = ref(null) // { path, dir } 正在拖拽的条目
const dragOverPath = ref('') // 当前高亮的可放置文件夹
const treeRootActive = ref(false) // 拖到树空白处 = 移到根目录

function canDropOn(row) {
  const src = dragSource.value
  if (!src || !row || !row.dir) return false
  if (src.path === row.path) return false // 不能放进自己
  if (src.dir && row.path.startsWith(src.path + '/')) return false // 不能放进自己子孙
  if (parentOf(src.path) === row.path) return false // 本来就在该文件夹里
  return true
}

function onRowDragStart(row, event) {
  if (isSystemFolder(row)) return // 系统文件夹不可拖走
  dragSource.value = { path: row.path, dir: !!row.dir }
  dragOverPath.value = ''
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', row.path)
  }
}

function endDrag() {
  dragSource.value = null
  dragOverPath.value = ''
}

function onRowDragOver(row, event) {
  if (!canDropOn(row)) return
  event.preventDefault() // 只有允许放置时才阻止默认，激活 drop
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  if (dragOverPath.value !== row.path) dragOverPath.value = row.path
}

function onRowDragLeave(row) {
  if (dragOverPath.value === row.path) dragOverPath.value = ''
}

function findNodeByPath(node, path) {
  if (!node) return null
  if (node.path === path) return node
  for (const child of node.children || []) {
    const found = findNodeByPath(child, path)
    if (found) return found
  }
  return null
}

function nameAvailableIn(folderPath, name) {
  const folder = findNodeByPath(tree.value, folderPath)
  if (!folder) return true
  const low = name.toLowerCase()
  return !(folder.children || []).some((c) => c.name.toLowerCase() === low)
}

// 目标目录下自动找一个可用文件名（重名加 " (n)"，n 从 1 递增）
function freeName(folderPath, name) {
  if (nameAvailableIn(folderPath, name)) return name
  const dot = name.lastIndexOf('.')
  const stem = dot > 0 ? name.slice(0, dot) : name
  const ext = dot > 0 ? name.slice(dot) : ''
  for (let i = 1; i < 100; i++) {
    const cand = stem + ' (' + i + ')' + ext
    if (nameAvailableIn(folderPath, cand)) return cand
  }
  return stem + ' (' + Date.now() + ')' + ext
}

async function onRowDrop(row, event) {
  event.preventDefault()
  event.stopPropagation()
  const src = dragSource.value
  const allowed = !!src && canDropOn(row)
  const targetPath = row.path
  endDrag()
  if (!allowed) return
  const name = freeName(targetPath, baseName(src.path))
  const to = joinPath(targetPath, name)
  try {
    await moveEntry(src.path, to, src.dir)
    toast(`已移动「${baseName(src.path)}」到「${targetPath || '根目录'}」`)
  } catch (e) {
    toast(e?.message || '移动失败')
  }
}

// 拖到目录树空白处：文件夹 → 根目录；笔记 → 「未分类」
const rootTargetHint = ref('')
function onTreeDragOver(event) {
  const src = dragSource.value
  if (!src || dragOverPath.value) return
  if (event.target?.closest?.('.tree-row')) return // 悬停在行上时不激活根目录落点
  rootTargetHint.value = src.dir ? '松开以移动到根目录' : `松开以移动到「${UNCLASSIFIED}」`
  if (parentOf(src.path) === '') return // 已在根目录/未分类所属场景无需移动
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  treeRootActive.value = true
}

function onTreeDragLeave(event) {
  // 只有离开整个 nav 时才取消；进入行区域由行内 dragOver 接管
  if (!event.currentTarget.contains(event.relatedTarget)) {
    treeRootActive.value = false
  }
}

async function onTreeDrop(event) {
  event.preventDefault()
  treeRootActive.value = false
  const src = dragSource.value
  endDrag()
  if (!src) return
  const dest = src.dir ? '' : UNCLASSIFIED // 文件夹回根；笔记进未分类
  if (parentOf(src.path) === dest) return // 本来就在那里
  const name = freeName(dest, baseName(src.path))
  const to = joinPath(dest, name)
  const shown = dest || '根目录'
  try {
    await moveEntry(src.path, to, src.dir)
    toast(`已移动「${baseName(src.path)}」到「${shown}」`)
  } catch (e) {
    toast(e?.message || '移动失败')
  }
}

const rows = computed(() => {
  const q = (filter.value || '').trim().toLowerCase()
  const out = []

  if (q) {
    // 搜索模式：扁平列出所有命中的笔记
    function collect(node) {
      if (!node) return
      if (!isDir(node)) {
        if (node.name.toLowerCase().includes(q)) {
          out.push({ name: node.name, path: node.path, type: 'file', depth: 0, dir: false })
        }
        return
      }
      for (const child of node.children || []) collect(child)
    }
    collect(tree.value)
    return out
  }

  // 普通模式：按开合状态递归展开目录（收起时其内部文件与子文件夹都不显示）
  function walk(node, depth, blocked) {
    if (!node) return
    if (!isDir(node)) {
      if (!blocked) {
        out.push({ name: node.name, path: node.path, type: 'file', depth, dir: false })
      }
      return
    }
    if (node.path !== '' && !blocked) {
      out.push({
        name: node.name,
        path: node.path,
        type: 'dir',
        depth,
        dir: true,
        open: openPaths.value.has(node.path)
      })
    }
    // 根节点(path==='')永远视为展开：目录根的直属内容默认可见
    const isOpen = node.path === '' || openPaths.value.has(node.path)
    const childBlocked = blocked || !isOpen
    for (const child of node.children || []) walk(child, depth + 1, childBlocked)
  }

  walk(tree.value, 0, false)
  return out
})

const fileCount = computed(() => {
  let n = 0
  function count(node) {
    if (!node) return
    for (const child of node.children || []) {
      if (isDir(child)) count(child)
      else if (child.name.toLowerCase().endsWith('.md')) n++
    }
  }
  count(tree.value)
  return n
})

// ---------------- 当前笔记 ----------------
const currentPath = ref('')
const text = ref('')
const lastSaved = ref('')
const saving = ref(false)
const loadedPath = ref('')
const status = ref('idle') // idle | saved | saving | error
const lastSavedAt = ref(0)

const dirty = computed(() => text.value !== lastSaved.value)
const hasFile = computed(() => !!currentPath.value)

const currentName = computed(() => (currentPath.value ? baseName(currentPath.value) : ''))
const currentDir = computed(() => parentOf(currentPath.value))

const rendered = computed(() => {
  if (!hasFile.value) return ''
  const html = marked.parse(text.value, { gfm: true, breaks: true })
  return DOMPurify.sanitize(html)
})

let saveTimer = null
function scheduleSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(flushSave, 800)
}

async function flushSave() {
  if (!hasFile.value || saving.value || !dirty.value) return
  clearTimeout(saveTimer)
  saving.value = true
  status.value = 'saving'
  const snapshot = text.value
  try {
    const res = await saveNote(currentPath.value, snapshot)
    lastSaved.value = snapshot
    lastSavedAt.value = res?.modified || Date.now()
    status.value = 'saved'
  } catch (e) {
    status.value = 'error'
    toast(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

watch(text, (value) => {
  if (currentPath.value && value !== lastSaved.value && loadedPath.value === currentPath.value) {
    status.value = dirty.value ? 'dirty' : status.value
    scheduleSave()
  }
})

let openSeq = 0
async function openNote(path) {
  if (path === currentPath.value && loadedPath.value === path) return
  await flushSave()
  const token = ++openSeq
  try {
    const file = await getNote(path)
    if (token !== openSeq) return // 期间用户已切换/清空，丢弃过期结果
    currentPath.value = path
    loadedPath.value = path
    text.value = file.content || ''
    lastSaved.value = file.content || ''
    lastSavedAt.value = file.modified || 0
    status.value = 'saved'
    await nextTick()
    previewEl.value?.scrollTo({ top: 0 })
    ensureVisible(path)
  } catch (e) {
    if (token !== openSeq) return
    toast(e?.message || '读取笔记失败')
    loadedPath.value = ''
  }
}

function ensureVisible(path) {
  const next = new Set(openPaths.value)
  let p = parentOf(path)
  while (p) {
    next.add(p)
    const pp = parentOf(p)
    if (pp === p) break
    p = pp
  }
  openPaths.value = next
}

function onEditorInput(e) {
  text.value = e.target.value
}

function onKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 's') {
    e.preventDefault()
    flushSave()
    return
  }
  if (e.key === 'Tab') {
    e.preventDefault()
    const el = e.target
    const start = el.selectionStart
    const end = el.selectionEnd
    text.value = text.value.slice(0, start) + '  ' + text.value.slice(end)
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = start + 2
    })
  }
}

// ---------------- 结构操作（新建/重命名/删除） ----------------
const modal = ref(null) // { mode:'file'|'dir'|'rename', parent, from, dir }
const modalValue = ref('')
const modalBusy = ref(false)
const modalError = ref('')

function openNewNote(parent) {
  modal.value = { mode: 'file', parent: parent == null ? noteParent() : parent }
  modalValue.value = ''
  modalError.value = ''
}
function openNewDir(parent) {
  modal.value = { mode: 'dir', parent: parent == null ? dirParent() : parent }
  modalValue.value = ''
  modalError.value = ''
}
function openRename(row) {
  modal.value = {
    mode: 'rename',
    parent: parentOf(row.path),
    from: row.path,
    dir: !!row.dir,
    original: baseName(row.path)
  }
  modalValue.value = baseName(row.path)
  modalError.value = ''
}
function closeModal() {
  if (modalBusy.value) return
  modal.value = null
  modalValue.value = ''
  modalError.value = ''
}

async function submitModal() {
  if (!modal.value || modalBusy.value) return
  const m = modal.value
  const raw = modalValue.value.trim()
  if (!raw) {
    modalError.value = '请输入名称'
    return
  }
  modalBusy.value = true
  modalError.value = ''
  try {
    if (m.mode === 'file') {
      const name = raw.toLowerCase().endsWith('.md') ? raw : raw + '.md'
      const path = joinPath(m.parent, name)
      await saveNote(path, `# ${baseName(path).replace(/\.md$/i, '')}\n\n`)
      await loadTree()
      selectedDir.value = m.parent
      selectedPath.value = path
      viewMode.value = 'edit' // 新建完成后直接进入编辑
      await openNote(path)
    } else if (m.mode === 'dir') {
      const path = joinPath(m.parent, raw)
      await createDir(path)
      await loadTree()
      ensureVisible(path)
      // 新建后即进入该文件夹，便于立刻在里面继续新建
      selectedDir.value = path
      selectedPath.value = path
      openPaths.value = new Set([...openPaths.value, path])
    } else if (m.mode === 'rename') {
      await moveEntry(m.from, joinPath(m.parent, raw), !!m.dir)
    }
    closeModal()
  } catch (e) {
    modalError.value = e?.message || '操作失败'
  } finally {
    modalBusy.value = false
  }
}

// 文件夹删除方式（整体回收站 / 笔记平铺到未分类）
const folderDelete = ref(null) // { path, name, busy }

function askDeleteFolder(row) {
  folderDelete.value = { path: row.path, name: row.name, busy: false }
}

async function submitFolderDelete(mode) {
  const fd = folderDelete.value
  if (!fd || fd.busy) return
  fd.busy = true
  try {
    if (mode === 'trash') {
      await deleteFolder(fd.path, 'trash')
      toast(`文件夹「${fd.name}」已移入回收站`)
    } else {
      await deleteFolder(fd.path, 'flatten')
      toast(`文件夹「${fd.name}」已删除，笔记已移入「${UNCLASSIFIED}」`)
    }
    clearCurrentIfInside(fd.path)
    fixSelectionAfterRemove(fd.path)
    folderDelete.value = null
    await refreshAll()
  } catch (e) {
    toast(e?.message || '删除失败')
  } finally {
    if (folderDelete.value) folderDelete.value.busy = false
  }
}

function clearCurrentIfInside(path) {
  if (currentPath.value === path || currentPath.value?.startsWith(path + '/')) {
    clearCurrent()
  }
}

async function removeRow(row) {
  if (row.dir) {
    askDeleteFolder(row)
    return
  }
  if (!window.confirm(`删除笔记「${row.name}」？将移入回收站，7 天后自动清除。`)) return
  try {
    await deleteNote(row.path)
    clearCurrentIfInside(row.path)
    fixSelectionAfterRemove(row.path)
    toast('已移入回收站')
    await refreshAll()
  } catch (e) {
    toast(e?.message || '删除失败')
  }
}

async function deleteCurrent() {
  if (!currentPath.value) return
  if (!window.confirm(`删除笔记「${currentPath.value}」？将移入回收站，7 天后自动清除。`)) return
  try {
    const removedPath = currentPath.value
    await deleteNote(removedPath)
    clearCurrent()
    fixSelectionAfterRemove(removedPath)
    toast('已移入回收站')
    await refreshAll()
  } catch (e) {
    toast(e?.message || '删除失败')
  }
}

// ---------------- 回收站 ----------------
async function refreshTrash() {
  trashError.value = ''
  try {
    trashItems.value = await getTrash()
  } catch (e) {
    trashError.value = e?.message || '读取回收站失败'
  }
}

async function refreshAll() {
  await Promise.all([loadTree(), refreshTrash()])
}

function openTrash() {
  trashOpen.value = true
  refreshTrash()
}

function fmtDeleted(ms) {
  if (!ms) return ''
  const d = new Date(ms)
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const days = Math.floor((now - d) / 86400000)
  const left = 7 - days
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}${left > 0 ? `（${left} 天后自动清除）` : ''}`
}

async function restoreItem(item) {
  try {
    await restoreTrash(item.id)
    await refreshAll()
    toast(`已恢复「${item.name}」`)
  } catch (e) {
    toast(e?.message || '恢复失败')
  }
}

async function removeTrashItem(item) {
  if (!window.confirm(`永久删除「${item.name}」？此操作不可恢复。`)) return
  try {
    await deleteTrashEntry(item.id)
    await refreshTrash()
  } catch (e) {
    toast(e?.message || '删除失败')
  }
}

async function emptyTrash() {
  if (!trashItems.value.length) return
  if (!window.confirm(`清空回收站（${trashItems.value.length} 项将永久删除）？`)) return
  try {
    await clearTrashAll()
    trashItems.value = []
  } catch (e) {
    toast(e?.message || '清空失败')
  }
}

function clearCurrent() {
  openSeq++ // 使在途的 openNote 结果作废
  currentPath.value = ''
  loadedPath.value = ''
  text.value = ''
  lastSaved.value = ''
  status.value = 'idle'
}

// ---------------- 移动端布局与视图模式 ----------------
const mobile = ref(false)
const showTree = ref(false)
// 视图模式：edit=左侧语法输入 + 右侧实时渲染；preview=仅渲染成品
const viewMode = ref('edit')
const editorEl = ref(null)
const mq = window.matchMedia('(max-width: 1080px)')

function setView(mode) {
  viewMode.value = mode
  if (mode === 'edit') {
    nextTick(() => editorEl.value?.focus())
  }
}

function onMqChange(e) {
  mobile.value = e.matches
  if (!e.matches) showTree.value = false
}

// ---------------- Toast ----------------
const toastMsg = ref('')
let toastTimer = null
function toast(msg) {
  toastMsg.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastMsg.value = ''), 3200)
}

// ---------------- 顶部动作 ----------------
const previewEl = ref(null)

async function logout() {
  try {
    await logoutApi()
  } catch {
    /* 本地登出优先 */
  }
  clearAuth()
  router.push({ name: 'login' })
}

function goChat() {
  router.push({ name: 'chat' })
}
function goStats() {
  router.push({ name: 'stats' })
}

onMounted(() => {
  mq.addEventListener('change', onMqChange)
  onMqChange(mq)
  refreshAll()
  window.addEventListener('beforeunload', flushSave)
})

onBeforeUnmount(() => {
  mq.removeEventListener('change', onMqChange)
  window.removeEventListener('beforeunload', flushSave)
  clearTimeout(saveTimer)
  flushSave()
})
</script>

<template>
  <div class="app notes-app">
    <header class="topbar">
      <div class="brand">
        <button v-if="mobile" class="icon-btn tree-toggle" title="笔记列表" @click="showTree = !showTree">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M4 6h16M4 12h16M4 18h10" />
          </svg>
        </button>
        <div class="brand-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
          </svg>
        </div>
        <div class="brand-text">
          <span class="brand-name">Markdown 笔记</span>
          <span class="brand-tag">{{ user?.displayName || user?.username || '未登录' }} · {{ fileCount }} 篇</span>
        </div>
      </div>

      <div class="topbar-actions">
        <span class="desktop-only"><button class="nav-btn" @click="goStats">效率统计</button></span>
        <button class="nav-btn" @click="goChat">返回聊天</button>
        <span class="desktop-only"><button class="icon-btn" title="切换主题" @click="toggleTheme">
          <svg v-if="theme === 'dark'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </button></span>
        <button class="icon-btn" title="退出登录" @click="logout">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <path d="m16 17 5-5-5-5" />
            <path d="M21 12H9" />
          </svg>
        </button>
      </div>
    </header>

    <div class="notes-shell">
      <!-- 左：目录树 -->
      <aside class="notes-side" :class="{ 'mobile-open': showTree }">
        <div class="side-head">
          <div>
            <h2>笔记</h2>
            <p class="side-sub">选中文件夹后新建进入其中 · 否则进「未分类」</p>
          </div>
          <div class="side-actions">
            <button
              class="icon-btn small"
              :title="'新建笔记（目标：' + noteParent() + '）'"
              @click="openNewNote()"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3Z" /></svg>
            </button>
            <button
              class="icon-btn small"
              :title="'新建文件夹（目标：' + (dirParent() || '根目录') + '）'"
              @click="openNewDir()"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /><path d="M12 11v5M9.5 13.5h5" /></svg>
            </button>
          </div>
        </div>

        <label class="side-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
          <input v-model="filter" type="search" placeholder="搜索笔记" />
        </label>

        <div v-if="loadingTree" class="side-hint">载入目录…</div>
        <div v-else-if="treeError" class="side-hint error">{{ treeError }}</div>

        <nav
          v-else
          class="tree"
          :class="{ 'root-target': treeRootActive }"
          aria-label="笔记列表"
          @dragover="onTreeDragOver"
          @dragleave="onTreeDragLeave"
          @drop="onTreeDrop"
        >
          <button
            v-for="row in rows"
            :key="row.path"
            class="tree-row"
            :class="{
              active: selectedPath === row.path,
              folder: row.dir,
              'drag-source': dragSource?.path === row.path,
              'drop-target': dragOverPath === row.path,
              droppable: !!dragSource && row.dir && canDropOn(row)
            }"
            :style="{ paddingLeft: 10 + row.depth * 16 + 'px' }"
            draggable="true"
            @click="onRowClick(row)"
            @dragstart="onRowDragStart(row, $event)"
            @dragend="endDrag"
            @dragover="onRowDragOver(row, $event)"
            @dragleave="onRowDragLeave(row)"
            @drop="onRowDrop(row, $event)"
          >
            <span v-if="row.dir" class="tree-caret">
              <svg :class="{ rotated: row.open }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m9 18 6-6-6-6" /></svg>
            </span>
            <svg v-else class="tree-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 2h8l4 4v16H6Z" /><path d="M14 2v4h4" />
            </svg>
            <span class="tree-name">{{ row.name }}</span>
            <span class="tree-tools" @click.stop>
              <button v-if="row.dir" title="在此新建笔记" @click="openNewNote(row.path)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3Z" /></svg>
              </button>
              <button v-if="!isSystemFolder(row)" title="重命名" @click="openRename(row)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82Z" /><path d="M7 7h.01" /></svg>
              </button>
              <button v-if="!isSystemFolder(row)" title="删除" @click="removeRow(row)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" /></svg>
              </button>
            </span>
          </button>

          <div v-if="!rows.length && !filter" class="side-empty">
            <p>还没有笔记</p>
            <button class="primary-mini" type="button" @click="openNewNote()">新建第一篇笔记</button>
          </div>
          <div v-else-if="!rows.length && filter" class="side-empty"><p>没有匹配的笔记</p></div>
          <div v-if="treeRootActive" class="root-hint">{{ rootTargetHint }}</div>
        </nav>

        <footer v-if="mobile" class="side-foot">
          <button class="nav-btn" style="width: 100%" @click="showTree = false">收起列表</button>
        </footer>

        <footer class="side-trash-bar">
          <button type="button" class="trash-btn" @click="openTrash">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" /></svg>
            <span>回收站</span>
            <em v-if="trashCount">{{ trashCount }}</em>
            <small>7 天自动清除</small>
          </button>
        </footer>
      </aside>
      <div v-if="mobile && showTree" class="tree-mask" @click="showTree = false"></div>

      <!-- 工作区：编辑时双栏，预览时仅显示渲染结果 -->
      <section class="work-pane">
        <div v-if="hasFile" class="pane-head">
          <div class="file-title">
            <div class="file-name" :title="currentPath">{{ currentDir ? currentDir + ' / ' : '' }}<strong>{{ currentName }}</strong></div>
            <span
              class="save-state"
              :class="status"
              :title="lastSavedAt ? '上次保存 ' + new Date(lastSavedAt).toLocaleTimeString() : ''"
            >
              <i></i>
              <span v-if="status === 'saving'">保存中…</span>
              <span v-else-if="status === 'error'">保存失败</span>
              <span v-else-if="dirty">未保存</span>
              <span v-else>已保存</span>
            </span>
          </div>

          <div class="mode-seg" role="tablist" aria-label="视图切换">
            <button type="button" :class="{ active: viewMode === 'edit' }" @click="setView('edit')">编辑</button>
            <button type="button" :class="{ active: viewMode === 'preview' }" @click="setView('preview')">预览</button>
          </div>

          <div class="pane-actions">
            <button class="icon-btn small" :title="'新建笔记（目标：' + noteParent() + '）'" @click="openNewNote()">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3Z" /></svg>
            </button>
            <button class="icon-btn small" title="保存 (⌘S / Ctrl+S)" :disabled="saving" @click="flushSave">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" /><path d="M17 21v-8H7v8M7 3v5h8" /></svg>
            </button>
            <button class="icon-btn small danger" title="移入回收站" @click="deleteCurrent">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" /></svg>
            </button>
          </div>
        </div>

        <!-- 编辑模式：左侧 Markdown 源码，右侧实时渲染 -->
        <div v-if="hasFile && viewMode === 'edit'" class="edit-split">
          <section class="edit-source" aria-label="Markdown 语法输入区">
            <textarea
              v-model="text"
              ref="editorEl"
              class="md-editor"
              spellcheck="false"
              autocomplete="off"
              wrap="soft"
              placeholder="在这里输入 Markdown…"
              @input="onEditorInput"
              @keydown="onKeydown"
              @blur="flushSave"
            ></textarea>
            <div class="editor-statusbar">
              <span>{{ text.split('\n').length }} 行 · {{ text.length }} 字符</span>
              <span>支持 GFM / ⌘S 立即保存</span>
            </div>
          </section>

          <section ref="previewEl" class="preview-scroll edit-preview" aria-label="Markdown 实时渲染区">
            <article class="markdown md-preview" v-html="rendered"></article>
          </section>
        </div>

        <!-- 预览模式：只剩渲染后的成品 -->
        <div v-else-if="hasFile && viewMode === 'preview'" ref="previewEl" class="preview-scroll preview-only">
          <article class="markdown md-preview" v-html="rendered"></article>
        </div>

        <div v-else class="pane-empty">
          <div class="empty-orb">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3Z" /></svg>
          </div>
          <p class="empty-title">选择一篇笔记开始编辑</p>
          <p class="empty-sub">左侧是目录树，也可以新建笔记或文件夹</p>
          <button class="primary-mini" type="button" @click="openNewNote()">＋ 新建笔记</button>
        </div>
      </section>
    </div>

    <!-- 新建 / 重命名弹窗 -->
    <div v-if="modal" class="modal-mask" @click.self="closeModal">
      <div class="modal-card">
        <h3>{{ modal.mode === 'rename' ? '重命名' : modal.mode === 'dir' ? '新建文件夹' : '新建笔记' }}</h3>
        <p v-if="modal.parent" class="modal-sub">位置：{{ modal.parent || '笔记根目录' }}</p>
        <div class="modal-input">
          <input
            v-model="modalValue"
            type="text"
            :placeholder="modal.mode === 'rename' ? '' : modal.mode === 'dir' ? '文件夹名称' : '笔记名称'"
            autofocus
            @keydown.enter="submitModal"
            @keydown.esc="closeModal"
          />
          <span v-if="modal.mode === 'file' && modalValue && !modalValue.toLowerCase().endsWith('.md')" class="ext-hint">.md</span>
        </div>
        <p v-if="modalError" class="modal-error">{{ modalError }}</p>
        <div class="modal-actions">
          <button class="nav-btn" type="button" @click="closeModal">取消</button>
          <button class="primary-mini" type="button" :disabled="modalBusy" @click="submitModal">
            {{ modalBusy ? '处理中…' : '确定' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 文件夹删除方式 -->
    <div v-if="folderDelete" class="modal-mask" @click.self="folderDelete = null">
      <div class="modal-card">
        <h3>删除文件夹「{{ folderDelete.name }}」</h3>
        <p class="modal-sub">文件夹里的笔记不会直接丢失，请选择：</p>
        <div class="choice-list">
          <button class="choice" type="button" :disabled="folderDelete.busy" @click="submitFolderDelete('trash')">
            <strong>整个文件夹移入回收站</strong>
            <span>保持目录结构，可整体恢复（7 天后自动清除）</span>
          </button>
          <button class="choice" type="button" :disabled="folderDelete.busy" @click="submitFolderDelete('flatten')">
            <strong>删除文件夹，笔记平铺移入「未分类」</strong>
            <span>文件夹删除，其中所有笔记保留在未分类</span>
          </button>
        </div>
        <div class="modal-actions">
          <button class="nav-btn" type="button" @click="folderDelete = null">取消</button>
        </div>
      </div>
    </div>

    <!-- 回收站抽屉 -->
    <div v-if="trashOpen" class="trash-mask" @click="trashOpen = false"></div>
    <transition name="slide">
      <aside v-if="trashOpen" class="trash-drawer" aria-label="回收站">
        <header class="trash-head">
          <div>
            <h3>回收站</h3>
            <p class="side-sub">条目保留 7 天，超期自动清除</p>
          </div>
          <div class="pane-actions">
            <button class="icon-btn small" title="清空回收站" :disabled="!trashItems.length" @click="emptyTrash">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" /></svg>
            </button>
            <button class="icon-btn small" title="关闭" @click="trashOpen = false">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
            </button>
          </div>
        </header>
        <div class="trash-body">
          <div v-if="trashLoading" class="side-hint">载入中…</div>
          <div v-else-if="trashError" class="side-hint error">{{ trashError }}</div>
          <div v-else-if="!trashItems.length" class="side-hint">回收站是空的</div>
          <ul v-else class="trash-list">
            <li v-for="item in trashItems" :key="item.id">
              <div class="trash-copy">
                <strong>{{ item.name }}</strong>
                <span>{{ item.originalPath }}</span>
                <small>{{ fmtDeleted(item.deletedAt) }}</small>
              </div>
              <div class="trash-actions">
                <button class="icon-btn small" title="恢复" @click="restoreItem(item)">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></svg>
                </button>
                <button class="icon-btn small danger" title="永久删除" @click="removeTrashItem(item)">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" /></svg>
                </button>
              </div>
            </li>
          </ul>
        </div>
      </aside>
    </transition>

    <transition name="fade">
      <div v-if="toastMsg" class="toast">{{ toastMsg }}</div>
    </transition>
  </div>
</template>

<style scoped>
.notes-app {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* 顶栏右侧操作区：统一垂直居中，文字/图标按按钮盒心对齐，防任何 display 覆写导致偏移 */
.topbar-actions {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
}
.topbar-actions .nav-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  flex: none;
}
.topbar-actions .icon-btn {
  display: grid;
  place-items: center;
  flex: none;
}

.desktop-only {
  display: none;
}
@media (min-width: 1081px) {
  .desktop-only {
    display: inline-flex;
    align-items: center;
  }
}
.mobile-only {
  display: none;
}
@media (max-width: 1080px) {
  .mobile-only {
    display: inline-flex;
  }
}

/* ---------- 三段式布局 ---------- */
.notes-shell {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}

.notes-side {
  width: 264px;
  flex: none;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--surface);
  min-height: 0;
}

.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 14px 6px;
}
.side-head h2 {
  font-size: 15px;
  font-weight: 680;
  letter-spacing: 0.01em;
}
.side-sub {
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--text-muted);
}
.side-actions {
  display: flex;
  gap: 6px;
}

.icon-btn.small {
  width: 30px;
  height: 30px;
  border-radius: 9px;
}
.icon-btn.danger:hover {
  color: var(--danger);
  border-color: var(--danger);
  background: rgba(248, 113, 113, 0.08);
}
.icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  transform: none;
}

.side-search {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 8px 14px;
  padding: 0 10px;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-2);
  color: var(--text-muted);
}
.side-search svg {
  width: 15px;
  height: 15px;
  flex: none;
}
.side-search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: none;
  color: var(--text);
  font-size: 13px;
}
.side-search input::placeholder {
  color: var(--text-muted);
}

.tree {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 4px 8px 10px;
}
.side-hint,
.side-empty {
  padding: 20px 18px;
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
}
.side-hint.error {
  color: var(--danger);
}
.side-empty {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
}

.tree-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 8px;
  padding-right: 4px;
  border-radius: 8px;
  color: var(--text-2);
  font-size: 13.5px;
  text-align: left;
  transition: background 0.14s ease;
}
.tree-row:hover {
  background: var(--surface-2);
  color: var(--text);
}
.tree-row.active {
  background: var(--accent-soft);
  color: var(--text);
  outline: 1.5px solid var(--accent);
  outline-offset: -1.5px;
}
.tree-row.active .tree-name {
  color: var(--accent);
}

/* 拖拽移动 */
.tree-row.drag-source {
  opacity: 0.45;
}
.tree-row.droppable {
  cursor: copy;
}
.tree-row.droppable .tree-name {
  color: var(--accent-2);
}
.tree-row.drop-target {
  background: var(--accent-soft);
  outline: 2px dashed var(--accent);
  outline-offset: -2px;
}
.tree-row.drop-target .tree-name {
  color: var(--accent);
}
.tree.root-target {
  outline: 2px dashed var(--accent-2);
  outline-offset: -4px;
  border-radius: 10px;
}
.tree.root-target::after {
  content: '松开以移动到根目录';
  display: block;
  text-align: center;
  color: var(--accent);
  font-size: 12px;
  padding: 6px 0 2px;
}

.tree-caret {
  width: 15px;
  height: 15px;
  flex: none;
  display: grid;
  place-items: center;
  color: var(--text-muted);
}
.tree-caret svg {
  width: 13px;
  height: 13px;
  transition: transform 0.16s ease;
}
.tree-caret svg.rotated {
  transform: rotate(90deg);
}
.tree-file-icon {
  width: 14px;
  height: 14px;
  flex: none;
  color: var(--text-muted);
  margin-left: 1px;
}
.tree-row.active .tree-file-icon {
  color: var(--accent);
}
.tree-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-tools {
  display: none;
  gap: 2px;
  flex: none;
}
.tree-row:hover .tree-tools {
  display: inline-flex;
}
.tree-tools button {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  color: var(--text-muted);
}
.tree-tools button:hover {
  color: var(--danger);
  background: var(--surface-2);
}
.tree-tools button:first-child:hover {
  color: var(--accent);
}
.tree-tools svg {
  width: 14px;
  height: 14px;
}

.side-foot {
  padding: 10px;
  border-top: 1px solid var(--border);
}

/* ---------- 编辑区 / 预览区 ---------- */
.editor-pane,
.preview-pane {
  flex: 1 1 50%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-2);
}
.preview-pane {
  border-left: 1px solid var(--border);
  background: var(--bg);
}

.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  min-height: 50px;
}
.file-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.file-name {
  font-size: 13.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-name strong {
  color: var(--text);
  font-weight: 650;
}
.save-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-muted);
  flex: none;
}
.save-state i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-muted);
}
.save-state.saved i {
  background: #34d399;
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.16);
}
.save-state.saving i {
  background: var(--accent);
  animation: pulse 1s ease infinite;
}
.save-state.error i,
.save-state.dirty i {
  background: var(--danger);
  box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.16);
}
@keyframes pulse {
  50% {
    opacity: 0.35;
  }
}
.pane-actions {
  display: flex;
  gap: 6px;
}

.edit-split {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}
.edit-source {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-2);
}
.md-editor {
  flex: 1;
  width: 100%;
  min-height: 0;
  padding: 16px 18px;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: 1.75;
  tab-size: 2;
}
.md-editor::placeholder {
  color: var(--text-muted);
}
.editor-statusbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 14px;
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 11.5px;
}

.preview-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  min-height: 50px;
}
.preview-badge {
  font-size: 11.5px;
  letter-spacing: 0.08em;
  font-weight: 650;
  color: var(--accent);
  border: 1px solid var(--border-strong);
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
}
.preview-hint {
  font-size: 11.5px;
  color: var(--text-muted);
}
.preview-scroll {
  flex: 1;
  overflow: auto;
  padding: 18px 22px 44px;
}
.edit-preview {
  min-width: 0;
  min-height: 0;
  border-left: 1px solid var(--border);
  background: var(--bg);
}
.edit-preview .md-preview {
  padding: 32px 36px 48px;
}
.preview-only .md-preview {
  max-width: 920px;
}
/* 成品文档纸张：与左侧源码编辑器形成明显视觉区别 */
.md-preview {
  max-width: 820px;
  margin: 0 auto;
  padding: 40px 48px 60px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 16px;
  color: var(--text);
  font-size: 15.5px;
  line-height: 1.85;
}
.md-preview h1 {
  font-size: 1.9em;
  font-weight: 750;
  margin: 0.7em 0 0.5em;
  padding-bottom: 0.35em;
  border-bottom: 1px solid var(--border);
}
.md-preview h2 {
  font-size: 1.5em;
  font-weight: 720;
  margin-top: 1.3em;
}
.md-preview h3 {
  font-size: 1.22em;
  font-weight: 680;
  margin-top: 1.1em;
}
.md-preview h4 {
  font-size: 1.05em;
  font-weight: 650;
}
.md-preview p {
  margin: 0.65em 0;
}
.md-preview ul,
.md-preview ol {
  margin: 0.6em 0;
  padding-left: 1.8em;
}
.md-preview img {
  max-width: 100%;
  border-radius: 10px;
}
.md-preview blockquote {
  font-size: 0.98em;
}
.md-preview code {
  font-size: 0.9em;
}
.md-preview pre {
  font-size: 13px;
}
.md-preview > :first-child {
  margin-top: 0;
}

.pane-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  padding: 30px;
}

.seg {
  display: inline-flex;
  padding: 3px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  gap: 2px;
}
.seg button {
  padding: 5px 16px;
  border-radius: 7px;
  font-size: 12.5px;
  color: var(--text-2);
}
.seg button.active {
  background: var(--accent-grad);
  color: #17140c;
  font-weight: 650;
}

.primary-mini {
  padding: 8px 18px;
  border-radius: 10px;
  background: var(--accent-grad);
  color: #17140c;
  font-size: 13.5px;
  font-weight: 650;
  box-shadow: 0 8px 18px -8px var(--accent-ring);
}
.primary-mini:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ---------- 弹窗 & Toast ---------- */
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  display: grid;
  place-items: center;
  padding: 20px;
}
.modal-card {
  width: 380px;
  max-width: 100%;
  background: var(--surface-solid);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  padding: 20px;
  box-shadow: var(--shadow);
}
.modal-card h3 {
  font-size: 16px;
  font-weight: 680;
}
.modal-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
}
.modal-input {
  position: relative;
  display: flex;
  align-items: center;
  margin-top: 14px;
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  background: var(--bg-2);
  overflow: hidden;
}
.modal-input input {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border: none;
  outline: none;
  background: none;
  color: var(--text);
  font-size: 14px;
}
.modal-input input:focus {
  box-shadow: inset 0 0 0 1.5px var(--accent);
}
.ext-hint {
  padding-right: 12px;
  font-size: 13px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.modal-error {
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--danger);
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.toast {
  position: fixed;
  left: 50%;
  bottom: 26px;
  transform: translateX(-50%);
  z-index: 80;
  max-width: min(480px, 90vw);
  padding: 10px 18px;
  border-radius: 12px;
  background: var(--surface-solid);
  border: 1px solid var(--border-strong);
  color: var(--danger);
  font-size: 13.5px;
  box-shadow: var(--shadow);
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ---------- 移动端 ---------- */
@media (max-width: 1080px) {
  .notes-side {
    position: absolute;
    inset: 0 auto 0 0;
    width: 272px;
    z-index: 30;
    transform: translateX(-104%);
    transition: transform 0.22s ease;
    box-shadow: none;
    background: var(--surface-solid);
  }
  .notes-side.mobile-open {
    transform: translateX(0);
    box-shadow: var(--shadow);
  }
  .tree-mask {
    position: absolute;
    inset: 0;
    z-index: 29;
    background: rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(1.5px);
    -webkit-backdrop-filter: blur(1.5px);
  }
  .seg.mobile-only {
    display: flex;
    justify-content: center;
    align-self: center;
    border: 1px solid var(--border);
    background: var(--surface-2);
    padding: 4px;
    margin: 8px 14px 0;
  }
  .seg.mobile-only button {
    flex: 1;
    padding: 6px 22px;
  }
}

/* ---------- 选中状态 & 拖拽空投 ---------- */
.tree-tools button:first-child:not(:last-child) {
  color: var(--text-muted);
}
.tree-tools button:first-child:not(:last-child):hover {
  color: var(--accent);
}
.tree.root-target {
  outline: 2px dashed var(--accent-2);
  outline-offset: -4px;
  border-radius: 10px;
}
.tree.root-target::after {
  content: none;
}
.root-hint {
  margin: 8px 12px 4px;
  padding: 7px 10px;
  border-radius: 9px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12.5px;
  text-align: center;
}

/* ---------- 侧栏底部：回收站入口 ---------- */
.side-trash-bar {
  padding: 8px 10px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}
.side-trash-bar .trash-btn {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  color: var(--text-2);
  font-size: 13px;
  transition: all 0.15s ease;
}
.side-trash-bar .trash-btn:hover {
  color: var(--text);
  background: var(--surface-2);
}
.side-trash-bar .trash-btn svg {
  width: 15px;
  height: 15px;
  color: var(--text-muted);
}
.side-trash-bar .trash-btn em {
  font-style: normal;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--accent-grad);
  color: #17140c;
  font-size: 11.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.side-trash-bar .trash-btn small {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 10.5px;
}

/* ---------- 文件夹删除方式选择 ---------- */
.choice-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}
.choice {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 13px;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: var(--bg-2);
  color: var(--text);
  transition: all 0.15s ease;
}
.choice:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.choice:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.choice strong {
  font-size: 13.5px;
  font-weight: 650;
}
.choice span {
  font-size: 12px;
  color: var(--text-muted);
}

/* ---------- 回收站抽屉 ---------- */
.trash-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(0, 0, 0, 0.42);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}
.trash-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 61;
  width: 360px;
  max-width: 92vw;
  display: flex;
  flex-direction: column;
  background: var(--surface-solid);
  border-left: 1px solid var(--border-strong);
  box-shadow: var(--shadow);
}
.trash-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 18px 16px 12px;
  border-bottom: 1px solid var(--border);
}
.trash-head h3 {
  font-size: 16px;
  font-weight: 680;
}
.trash-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px 20px;
}
.trash-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.trash-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: var(--bg-2);
}
.trash-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.trash-copy strong {
  font-size: 13.5px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trash-copy span,
.trash-copy small {
  font-size: 11.5px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trash-actions {
  display: flex;
  gap: 5px;
  flex: none;
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.22s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}

/* ---------- 工作区（编辑/预览二选一） ---------- */
.work-pane {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-2);
}
.work-pane .pane-head {
  flex-wrap: nowrap;
}
.work-pane .file-title {
  flex: 1 1 auto;
  min-width: 0;
}
.mode-seg {
  display: inline-flex;
  flex: none;
  padding: 3px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  gap: 2px;
}
.mode-seg button {
  padding: 5px 18px;
  border-radius: 7px;
  font-size: 12.5px;
  color: var(--text-2);
  transition: all 0.15s ease;
}
.mode-seg button:hover {
  color: var(--text);
}
.mode-seg button.active {
  background: var(--accent-grad);
  color: #17140c;
  font-weight: 650;
}
@media (max-width: 700px) {
  .edit-split {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(240px, 1fr) minmax(240px, 1fr);
    overflow: auto;
  }
  .edit-source,
  .edit-preview {
    min-height: 240px;
  }
  .edit-preview {
    border-left: none;
    border-top: 1px solid var(--border);
  }
}
@media (max-width: 560px) {
  .mode-seg button {
    padding: 5px 12px;
  }
  .work-pane .pane-actions .icon-btn.small:first-child {
    display: none; /* 极窄屏隐藏“新建笔记”，避免挤爆标题 */
  }
}
</style>
