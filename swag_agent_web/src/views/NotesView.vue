<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { getTree, getNote, saveNote, deleteNote, createDir, deleteDir, renameEntry } from '../api/notes'
import { getUser, clearAuth } from '../auth'
import { currentTheme, applyTheme } from '../theme'
import { logout as logoutApi } from '../api/auth'

const router = useRouter()
const user = getUser()

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

  // 普通模式：按开合状态递归展开目录
  function walk(node, depth, blocked) {
    if (!node) return
    if (!isDir(node)) {
      out.push({ name: node.name, path: node.path, type: 'file', depth, dir: false })
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
    const childBlocked = blocked || (node.path !== '' && !openPaths.value.has(node.path))
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
    if (mobile.value) mobileTab.value = 'edit'
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
const modal = ref(null) // { mode:'file'|'dir'|'rename', parent, from, hint }
const modalValue = ref('')
const modalBusy = ref(false)
const modalError = ref('')

function openNewNote() {
  modal.value = { mode: 'file', parent: currentDir.value }
  modalValue.value = ''
  modalError.value = ''
}
function openNewDir() {
  modal.value = { mode: 'dir', parent: currentDir.value }
  modalValue.value = ''
  modalError.value = ''
}
function openRename(row) {
  modal.value = {
    mode: 'rename',
    parent: parentOf(row.path),
    from: row.path,
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
      await openNote(path)
    } else if (m.mode === 'dir') {
      await createDir(joinPath(m.parent, raw))
      await loadTree()
      ensureVisible(joinPath(m.parent, raw))
    } else if (m.mode === 'rename') {
      await flushSave() // 先落盘再改名，避免旧路径上残留未保存内容
      await renameEntry(m.from, joinPath(m.parent, raw))
      const mapped = joinPath(m.parent, raw)
      await loadTree()
      if (currentPath.value === m.from || currentPath.value?.startsWith(m.from + '/')) {
        const old = currentPath.value
        const suffix = old.slice(m.from.length)
        if (old === m.from) await openNote(mapped)
        else await openNote(mapped + suffix)
      }
    }
    closeModal()
  } catch (e) {
    modalError.value = e?.message || '操作失败'
  } finally {
    modalBusy.value = false
  }
}

async function removeRow(row) {
  const kind = row.dir ? '文件夹' : '笔记'
  const warning = row.dir ? '（将连同其中所有笔记一起删除，不可恢复）' : ''
  if (!window.confirm(`确定删除${kind}「${row.name}」？${warning}`)) return
  try {
    if (row.dir) await deleteDir(row.path)
    else await deleteNote(row.path)
    if (currentPath.value === row.path || currentPath.value?.startsWith(row.path + '/')) {
      clearCurrent()
    }
    await loadTree()
  } catch (e) {
    toast(e?.message || '删除失败')
  }
}

async function deleteCurrent() {
  if (!currentPath.value) return
  if (!window.confirm(`确定删除笔记「${currentPath.value}」？`)) return
  try {
    await deleteNote(currentPath.value)
    clearCurrent()
    await loadTree()
  } catch (e) {
    toast(e?.message || '删除失败')
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

// ---------------- 移动端布局 ----------------
const mobile = ref(false)
const showTree = ref(false)
const mobileTab = ref('edit') // edit | preview
const mq = window.matchMedia('(max-width: 1080px)')

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
  loadTree()
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
        <button class="nav-btn desktop-only" @click="goStats">效率统计</button>
        <button class="nav-btn" @click="goChat">返回聊天</button>
        <button class="icon-btn desktop-only" title="切换主题" @click="toggleTheme">
          <svg v-if="theme === 'dark'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </button>
        <button class="icon-btn" title="退出登录" @click="logout">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <path d="m16 17 5-5-5-5" />
            <path d="M21 12H9" />
          </svg>
        </button>
      </div>
    </header>

    <div class="notes-shell" :class="{ 'mobile-tab-edit': mobile && mobileTab === 'edit', 'mobile-tab-preview': mobile && mobileTab === 'preview' }">
      <!-- 左：目录树 -->
      <aside class="notes-side" :class="{ 'mobile-open': showTree }">
        <div class="side-head">
          <div>
            <h2>笔记</h2>
            <p class="side-sub">.md · 自动保存</p>
          </div>
          <div class="side-actions">
            <button class="icon-btn small" title="新建笔记" @click="openNewNote">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
            </button>
            <button class="icon-btn small" title="新建文件夹" @click="openNewDir">
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

        <nav v-else class="tree" aria-label="笔记列表">
          <button
            v-for="row in rows"
            :key="row.path"
            class="tree-row"
            :class="{
              active: row.path === currentPath,
              folder: row.dir
            }"
            :style="{ paddingLeft: 10 + row.depth * 16 + 'px' }"
            @click="row.dir ? toggleOpen(row.path) : openNote(row.path)"
          >
            <span v-if="row.dir" class="tree-caret">
              <svg :class="{ rotated: row.open }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m9 18 6-6-6-6" /></svg>
            </span>
            <svg v-else class="tree-file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 2h8l4 4v16H6Z" /><path d="M14 2v4h4" />
            </svg>
            <span class="tree-name">{{ row.name }}</span>
            <span class="tree-tools" @click.stop>
              <button title="重命名" @click="openRename(row)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
              </button>
              <button title="删除" @click="removeRow(row)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" /></svg>
              </button>
            </span>
          </button>

          <div v-if="!rows.length && !filter" class="side-empty">
            <p>还没有笔记</p>
            <button class="primary-mini" type="button" @click="openNewNote">新建第一篇笔记</button>
          </div>
          <div v-else-if="!rows.length && filter" class="side-empty"><p>没有匹配的笔记</p></div>
        </nav>

        <footer v-if="mobile" class="side-foot">
          <button class="nav-btn" style="width: 100%" @click="showTree = false">收起列表</button>
        </footer>
      </aside>
      <div v-if="mobile && showTree" class="tree-mask" @click="showTree = false"></div>

      <!-- 中：编辑区 -->
      <section class="editor-pane">
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
          <div class="pane-actions">
            <button class="icon-btn small" title="新建笔记" @click="openNewNote">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
            </button>
            <button class="icon-btn small" title="保存 (⌘S / Ctrl+S)" :disabled="saving" @click="flushSave">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" /><path d="M17 21v-8H7v8M7 3v5h8" /></svg>
            </button>
            <button class="icon-btn small danger" title="删除这篇笔记" @click="deleteCurrent">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" /></svg>
            </button>
          </div>
        </div>
        <div v-if="hasFile" class="seg mobile-only">
          <button :class="{ active: mobileTab === 'edit' }" type="button" @click="mobileTab = 'edit'">编辑</button>
          <button :class="{ active: mobileTab === 'preview' }" type="button" @click="mobileTab = 'preview'">预览</button>
        </div>

        <div v-if="hasFile" class="editor-wrap">
          <textarea
            v-model="text"
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
        </div>
        <div v-else class="pane-empty">
          <div class="empty-orb">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
          </div>
          <p class="empty-title">选择一篇笔记开始编辑</p>
          <p class="empty-sub">左侧是目录树，也可以新建笔记或文件夹</p>
          <button class="primary-mini" type="button" @click="openNewNote">＋ 新建笔记</button>
        </div>
      </section>

      <!-- 右：渲染预览 -->
      <section class="preview-pane">
        <div v-if="hasFile" class="preview-scroll">
          <article class="markdown md-preview" v-html="rendered"></article>
        </div>
        <div v-else class="pane-empty">
          <p class="empty-sub">渲染结果会实时显示在这里</p>
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

.desktop-only {
  display: none;
}
@media (min-width: 1081px) {
  .desktop-only {
    display: inline-flex;
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
}
.tree-row.active .tree-name {
  color: var(--accent);
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

.editor-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
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

.preview-scroll {
  flex: 1;
  overflow: auto;
  padding: 22px 26px 40px;
}
.md-preview {
  max-width: 860px;
  margin: 0 auto;
  font-size: 15px;
  line-height: 1.75;
  color: var(--text);
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
  .editor-pane,
  .preview-pane {
    flex: 1 1 100%;
  }
  .mobile-tab-edit .preview-pane {
    display: none;
  }
  .mobile-tab-preview .editor-pane {
    display: none;
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
</style>
