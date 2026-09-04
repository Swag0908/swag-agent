<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  getBookmarks,
  createFolder,
  updateFolder,
  deleteFolder,
  createBookmark,
  updateBookmark,
  deleteBookmark
} from '../api/bookmarks'
import { getUser, clearAuth, authHeaders } from '../auth'
import { currentTheme, applyTheme } from '../theme'
import { logout as logoutApi } from '../api/auth'

const router = useRouter()
const user = getUser()

const library = ref({ folders: [], bookmarks: [], total: 0 })
const loading = ref(false)
const error = ref('')

const selectedFolderId = ref(null)
const unclassifiedOnly = ref(false)
const searchInput = ref('')
const query = ref('')

const theme = ref(currentTheme())
const faviconFailed = ref({})
const faviconIdx = ref({})
const cachedFaviconUrls = ref({})
const cachedObjectUrls = new Set()
let iconLoadSequence = 0

const folderModal = ref(false)
const folderSaving = ref(false)
const folderForm = ref({ id: null, name: '', parentId: null, mode: 'create' })

const bookmarkModal = ref(false)
const bookmarkSaving = ref(false)
const bookmarkForm = ref({
  id: null,
  name: '',
  url: '',
  description: '',
  iconUrl: '',
  folderId: null
})

const activeTitle = computed(() => {
  if (unclassifiedOnly.value) return '未分类'
  const node = folderRows.value.find((item) => item.id === selectedFolderId.value)
  return node?.name || '全部网站'
})

const folderRows = computed(() => {
  const rows = []
  function walk(nodes, depth) {
    for (const node of nodes) {
      rows.push({
        id: node.id,
        name: node.name,
        parentId: node.parentId ?? null,
        count: node.bookmarkCount,
        depth,
        hasChildren: !!node.children?.length
      })
      if (node.children?.length) walk(node.children, depth + 1)
    }
  }
  walk(library.value.folders || [], 0)
  return rows
})

const folderMap = computed(() => {
  const map = {}
  for (const row of folderRows.value) map[row.id] = row.name
  return map
})

const flatFolders = computed(() => {
  const rows = []
  function walk(nodes, depth) {
    for (const node of nodes) {
      rows.push({ id: node.id, name: node.name, depth })
      if (node.children?.length) walk(node.children, depth + 1)
    }
  }
  walk(library.value.folders || [], 0)
  return rows
})

const folderOptions = computed(() => {
  const excluded = new Set()
  if (folderForm.value.mode === 'edit') {
    const editingId = folderForm.value.id
    excluded.add(editingId)
    const folderMapById = new Map()
    for (const node of library.value.folders || []) collectNode(node, folderMapById)
    function collectDesc(id, target, set) {
      const children = (folderMapById.get(id)?.children || [])
      for (const child of children) {
        set.add(child.id)
        collectDesc(child.id, target, set)
      }
    }
    collectDesc(editingId, editingId, excluded)
  }
  return flatFolders.value.filter((item) => !excluded.has(item.id))
})

let searchTimer
watch(searchInput, (value) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    query.value = value.trim()
    load()
  }, 240)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const nextLibrary = await getBookmarks({
      folderId: selectedFolderId.value,
      q: query.value,
      unclassified: unclassifiedOnly.value
    })
    const loadSequence = ++iconLoadSequence
    releaseCachedIcons()
    faviconFailed.value = {}
    faviconIdx.value = {}
    library.value = nextLibrary
    void loadCachedIcons(nextLibrary.bookmarks || [], loadSequence)
  } catch (e) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function selectAll() {
  selectedFolderId.value = null
  unclassifiedOnly.value = false
  load()
}

function selectUnclassified() {
  selectedFolderId.value = null
  unclassifiedOnly.value = true
  load()
}

function selectFolder(id) {
  selectedFolderId.value = id
  unclassifiedOnly.value = false
  load()
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  applyTheme(theme.value)
}

async function logout() {
  try {
    await logoutApi()
  } catch {
    /* 本地登出优先 */
  }
  clearAuth()
  router.push({ name: 'login' })
}

/* ---------- 文件夹 CRUD ---------- */
function openCreateFolder(parentId) {
  const defaultParentId = parentId !== undefined
    ? parentId
    : (!unclassifiedOnly.value && selectedFolderId.value != null ? selectedFolderId.value : null)
  folderForm.value = { id: null, name: '', parentId: defaultParentId, mode: 'create' }
  folderModal.value = true
}

function openEditFolder(folder) {
  folderForm.value = {
    id: folder.id,
    name: folder.name,
    parentId: folder.parentId ?? null,
    mode: 'edit'
  }
  folderModal.value = true
}

async function saveFolder() {
  folderSaving.value = true
  error.value = ''
  try {
    const payload = {
      name: folderForm.value.name,
      parentId: folderForm.value.parentId || null
    }
    if (folderForm.value.mode === 'create') {
      await createFolder(payload)
    } else {
      await updateFolder(folderForm.value.id, payload)
    }
    folderModal.value = false
    await load()
  } catch (e) {
    error.value = e?.message || '保存失败'
  } finally {
    folderSaving.value = false
  }
}

async function removeFolder(folder) {
  if (!window.confirm(`确定删除文件夹「${folder.name}」吗？`)) return
  error.value = ''
  try {
    await deleteFolder(folder.id, false)
    if (selectedFolderId.value === folder.id) selectAll()
    else await load()
  } catch (e) {
    const message = e?.message || ''
    if (message.includes('不为空')) {
      const cascade = window.confirm(`${message} 如果继续，其中的网站和子文件夹也会被删除。`)
      if (!cascade) return
      try {
        await deleteFolder(folder.id, true)
        if (selectedFolderId.value === folder.id) selectAll()
        else await load()
      } catch (inner) {
        error.value = inner?.message || '删除失败'
      }
      return
    }
    error.value = message || '删除失败'
  }
}

/* ---------- 书签 CRUD ---------- */
function openCreateBookmark() {
  const currentFolderId = unclassifiedOnly.value || selectedFolderId.value == null
    ? null
    : selectedFolderId.value
  bookmarkForm.value = {
    id: null,
    name: '',
    url: '',
    description: '',
    iconUrl: '',
    folderId: currentFolderId
  }
  bookmarkModal.value = true
}

function openEditBookmark(bookmark) {
  bookmarkForm.value = {
    id: bookmark.id,
    name: bookmark.name,
    url: bookmark.url,
    description: bookmark.description || '',
    iconUrl: bookmark.iconUrl || '',
    folderId: bookmark.folderId ?? null
  }
  bookmarkModal.value = true
}

async function saveBookmark() {
  bookmarkSaving.value = true
  error.value = ''
  try {
    const payload = {
      name: bookmarkForm.value.name,
      url: bookmarkForm.value.url,
      description: bookmarkForm.value.description,
      iconUrl: bookmarkForm.value.iconUrl,
      folderId: bookmarkForm.value.folderId || null
    }
    if (bookmarkForm.value.id == null) {
      await createBookmark(payload)
    } else {
      await updateBookmark(bookmarkForm.value.id, payload)
    }
    bookmarkModal.value = false
    await load()
  } catch (e) {
    error.value = e?.message || '保存失败'
  } finally {
    bookmarkSaving.value = false
  }
}

async function removeBookmark(bookmark) {
  if (!window.confirm(`确定删除「${bookmark.name}」吗？`)) return
  error.value = ''
  try {
    await deleteBookmark(bookmark.id)
    await load()
  } catch (e) {
    error.value = e?.message || '删除失败'
  }
}

/* ---------- 展示辅助 ---------- */
function domain(url) {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

function faviconUrl(bookmark) {
  const cached = cachedFaviconUrls.value[bookmark.id]
  if (cached) return cached
  if (faviconFailed.value[bookmark.id]) return null
  const candidates = faviconCandidates(bookmark)
  const idx = faviconIdx.value[bookmark.id] ?? 0
  return candidates[idx] || null
}

function faviconCandidates(bookmark) {
  const list = []
  const custom = (bookmark.iconUrl || '').trim()
  if (custom) list.push(custom)
  let host
  try {
    host = new URL(bookmark.url).hostname
  } catch {
    host = bookmark.url
  }
  if (host) {
    // Google s2/favicons 大陆不可达，改为国内可达的 DNSPod 代理，再兜底直连站点 favicon.ico
    list.push(`https://statics.dnspod.cn/proxy_favicon/_/favicon?domain=${encodeURIComponent(host)}`)
    list.push(`https://${host}/favicon.ico`)
  }
  return list
}

function monogram(name) {
  const chars = Array.from(name || '').filter((c) => c.trim())
  return (chars[0] || '?').toUpperCase()
}

function hashString(value) {
  let hash = 0
  for (let i = 0; i < value.length; i++) {
    hash = (hash << 5) - hash + value.charCodeAt(i)
    hash |= 0
  }
  return Math.abs(hash)
}

function avatarStyle(bookmark) {
  const hue = hashString(bookmark.url || bookmark.name) % 360
  return {
    background: `linear-gradient(135deg, hsl(${hue} 72% 56%), hsl(${(hue + 52) % 360} 74% 50%))`
  }
}

function onFaviconError(bookmark) {
  const candidates = faviconCandidates(bookmark)
  const cur = faviconIdx.value[bookmark.id] ?? 0
  const next = cur + 1
  if (next < candidates.length) {
    faviconIdx.value = { ...faviconIdx.value, [bookmark.id]: next }
  } else {
    faviconFailed.value = { ...faviconFailed.value, [bookmark.id]: true }
  }
}

async function loadCachedIcons(bookmarks, loadSequence) {
  const icons = await Promise.all(bookmarks.map(async (bookmark) => {
    try {
      const res = await fetch(`/api/bookmarks/${bookmark.id}/icon`, {
        headers: authHeaders()
      })
      if (!res.ok) return null
      const blob = await res.blob()
      if (!blob.size) return null
      const url = URL.createObjectURL(blob)
      if (loadSequence !== iconLoadSequence) {
        URL.revokeObjectURL(url)
        return null
      }
      cachedObjectUrls.add(url)
      return [bookmark.id, url]
    } catch {
      return null
    }
  }))
  const next = {}
  for (const item of icons) {
    if (item) next[item[0]] = item[1]
  }
  if (loadSequence === iconLoadSequence) cachedFaviconUrls.value = next
}

function releaseCachedIcons() {
  for (const url of cachedObjectUrls) URL.revokeObjectURL(url)
  cachedObjectUrls.clear()
  cachedFaviconUrls.value = {}
}

function collectNode(node, map) {
  map.set(node.id, node)
  for (const child of node.children || []) collectNode(child, map)
}

onMounted(load)
onUnmounted(() => {
  iconLoadSequence++
  releaseCachedIcons()
})
</script>

<template>
  <div class="app sites-app">
    <header class="topbar">
      <div class="brand">
        <div class="brand-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
          </svg>
        </div>
        <div class="brand-text">
          <span class="brand-name">常用网站</span>
          <span class="brand-tag">{{ user?.displayName || user?.username || '未登录' }}</span>
        </div>
      </div>

      <div class="topbar-actions">
        <button class="nav-btn" @click="router.push({ name: 'notes' })">Markdown 笔记</button>
        <button class="nav-btn" @click="router.push({ name: 'chat' })">返回聊天</button>

        <button class="icon-btn" title="切换主题" @click="toggleTheme">
          <svg v-if="theme === 'dark'" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </button>

        <button class="icon-btn" title="退出登录" @click="logout">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <path d="m16 17 5-5-5-5" />
            <path d="M21 12H9" />
          </svg>
        </button>
      </div>
    </header>

    <main class="sites-layout">
      <aside class="sites-sidebar">
        <div class="sites-sidebar-head">
          <h2>文件夹</h2>
          <button class="icon-btn small" title="新建文件夹" @click="openCreateFolder()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
        </div>

        <label class="sites-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input v-model="searchInput" type="search" placeholder="搜索网站" />
        </label>

        <nav class="folder-tree">
          <button class="folder-row root" :class="{ active: !unclassifiedOnly && selectedFolderId == null }"
                  @click="selectAll">
            <span class="folder-row-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="3" width="7" height="7" rx="1.5" />
                <rect x="14" y="3" width="7" height="7" rx="1.5" />
                <rect x="3" y="14" width="7" height="7" rx="1.5" />
                <rect x="14" y="14" width="7" height="7" rx="1.5" />
              </svg>
            </span>
            <span class="folder-row-name">全部网站</span>
            <span class="folder-row-count">{{ library.total }}</span>
          </button>

          <div class="folder-tree-sep"></div>

          <button
            class="folder-row"
            :class="{ active: unclassifiedOnly }"
            :style="{ paddingLeft: 12 + 'px' }"
            @click="selectUnclassified"
          >
            <span class="folder-chevron"></span>
            <span class="folder-row-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M4 4h7l2 2h7v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4z" />
              </svg>
            </span>
            <span class="folder-row-name">未分类</span>
            <span class="folder-row-count">{{ library.bookmarks.filter((b) => b.folderId == null).length }}</span>
          </button>

          <div v-if="!folderRows.length" class="folder-tree-empty">还没有文件夹</div>
          <button
            v-for="folder in folderRows"
            :key="folder.id"
            class="folder-row"
            :class="{ active: !unclassifiedOnly && selectedFolderId === folder.id }"
            :style="{ paddingLeft: 12 + folder.depth * 16 + 'px' }"
            @click="selectFolder(folder.id)"
          >
            <span class="folder-chevron">
              <svg v-if="folder.hasChildren" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="m9 18 6-6-6-6" />
              </svg>
            </span>
            <span class="folder-row-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M4 4h7l2 2h7v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4z" />
              </svg>
            </span>
            <span class="folder-row-name">{{ folder.name }}</span>
            <span class="folder-row-count">{{ folder.count }}</span>
            <span class="folder-row-actions">
              <button class="folder-row-op" title="重命名" @click.stop="openEditFolder(folder)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
                </svg>
              </button>
              <button class="folder-row-op danger" title="删除" @click.stop="removeFolder({ id: folder.id, name: folder.name })">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 6h18" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                  <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </span>
          </button>
        </nav>
      </aside>

      <section class="sites-content">
        <div class="sites-toolbar">
          <div>
            <h1>{{ activeTitle }}</h1>
            <p>{{ library.bookmarks.length }} 个网站</p>
          </div>
          <button class="primary-btn" @click="openCreateBookmark">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            添加网站
          </button>
        </div>

        <p v-if="error" class="sites-error">{{ error }}</p>

        <div v-if="loading" class="sites-loading">
          <span></span>
          <span></span>
          <span></span>
        </div>

        <div v-else-if="!library.bookmarks.length" class="sites-empty">
          <div class="sites-empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                 stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="9" />
              <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
            </svg>
          </div>
          <h3>这里还没有网站</h3>
          <p>把常用网站收集起来，以后打开会更快。</p>
          <button class="primary-btn" @click="openCreateBookmark">添加第一个网站</button>
        </div>

        <div v-else class="sites-grid">
          <article v-for="bookmark in library.bookmarks" :key="bookmark.id" class="site-card">
            <div class="site-card-head">
              <a class="site-favicon" :href="bookmark.url" target="_blank" rel="noopener">
                <img
                  v-if="faviconUrl(bookmark)"
                  :src="faviconUrl(bookmark)"
                  :alt="bookmark.name"
                  loading="lazy"
                  @error="onFaviconError(bookmark)"
                />
                <span v-else :style="avatarStyle(bookmark)">{{ monogram(bookmark.name) }}</span>
              </a>
              <div class="site-card-actions">
                <button class="site-op" title="编辑" @click="openEditBookmark(bookmark)">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                       stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 20h9" />
                    <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
                  </svg>
                </button>
                <button class="site-op danger" title="删除" @click="removeBookmark(bookmark)">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                       stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3 6h18" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                    <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
            </div>

            <a class="site-name" :href="bookmark.url" target="_blank" rel="noopener">
              {{ bookmark.name }}
            </a>
            <a class="site-domain" :href="bookmark.url" target="_blank" rel="noopener">
              {{ domain(bookmark.url) }}
            </a>
            <p v-if="bookmark.description" class="site-desc">{{ bookmark.description }}</p>
            <div class="site-foot">
              <span v-if="bookmark.folderId != null" class="site-folder">
                {{ folderMap[bookmark.folderId] || '文件夹' }}
              </span>
              <span v-else class="site-folder muted">未分类</span>
            </div>
          </article>
        </div>
      </section>
    </main>

    <!-- 文件夹编辑弹窗 -->
    <div v-if="folderModal" class="sites-modal-mask" @click.self="folderModal = false">
      <form class="sites-modal" @submit.prevent="saveFolder">
        <div class="sites-modal-head">
          <h2>{{ folderForm.mode === 'create' ? '新建文件夹' : '编辑文件夹' }}</h2>
          <button type="button" class="modal-close" @click="folderModal = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <label class="modal-field">
          <span>名称</span>
          <input v-model="folderForm.name" type="text" autofocus placeholder="例如：开发工具" />
        </label>

        <label class="modal-field">
          <span>上级文件夹</span>
          <select v-model="folderForm.parentId">
            <option :value="null">根目录</option>
            <option v-for="folder in folderOptions" :key="folder.id" :value="folder.id">
              {{ '　'.repeat(folder.depth) }}{{ folder.name }}
            </option>
          </select>
        </label>

        <div class="modal-actions">
          <button type="button" class="ghost-btn" @click="folderModal = false">取消</button>
          <button type="submit" class="primary-btn" :disabled="folderSaving">
            {{ folderSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 网站编辑弹窗 -->
    <div v-if="bookmarkModal" class="sites-modal-mask" @click.self="bookmarkModal = false">
      <form class="sites-modal" @submit.prevent="saveBookmark">
        <div class="sites-modal-head">
          <h2>{{ bookmarkForm.id == null ? '添加网站' : '编辑网站' }}</h2>
          <button type="button" class="modal-close" @click="bookmarkModal = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <label class="modal-field">
          <span>名称</span>
          <input v-model="bookmarkForm.name" type="text" autofocus placeholder="例如：GitHub" />
        </label>

        <label class="modal-field">
          <span>网址</span>
          <input v-model="bookmarkForm.url" type="text" placeholder="例如：https://github.com" />
        </label>

        <label class="modal-field">
          <span>所属文件夹</span>
          <select v-model="bookmarkForm.folderId">
            <option :value="null">未分类</option>
            <option v-for="folder in flatFolders" :key="folder.id" :value="folder.id">
              {{ '　'.repeat(folder.depth) }}{{ folder.name }}
            </option>
          </select>
        </label>

        <label class="modal-field">
          <span>备注</span>
          <textarea v-model="bookmarkForm.description" rows="3" placeholder="可选，简单记录用途"></textarea>
        </label>

        <label class="modal-field">
          <span>图标地址（可选）</span>
          <input v-model="bookmarkForm.iconUrl" type="text" placeholder="留空则自动获取网站图标" />
        </label>

        <div class="modal-actions">
          <button type="button" class="ghost-btn" @click="bookmarkModal = false">取消</button>
          <button type="submit" class="primary-btn" :disabled="bookmarkSaving">
            {{ bookmarkSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.sites-app {
  background: var(--bg);
}

.sites-layout {
  position: relative;
  z-index: 5;
  flex: 1;
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
}

.sites-sidebar {
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 20px 14px 18px;
  border-right: 1px solid var(--border);
  background: var(--surface);
  overflow-y: auto;
}

.sites-sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 6px 12px;
}

.sites-sidebar-head h2 {
  font-size: 15px;
  font-weight: 680;
}

.icon-btn.small {
  width: 30px;
  height: 30px;
  border-radius: 9px;
}

.icon-btn.small svg {
  width: 15px;
  height: 15px;
}

.sites-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 11px;
  margin: 0 2px 14px;
  border-radius: 11px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-muted);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.sites-search:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.sites-search svg {
  width: 16px;
  height: 16px;
  flex: none;
}

.sites-search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
}

.sites-search input::placeholder {
  color: var(--text-muted);
}

.folder-tree {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.folder-tree-empty {
  padding: 20px 12px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12.5px;
}

.folder-tree-sep {
  height: 1px;
  margin: 7px 2px;
  background: var(--border);
}

.folder-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 0 8px;
  border-radius: 10px;
  border: 1px solid transparent;
  color: var(--text-2);
  font-size: 13px;
  text-align: left;
  transition: background 0.16s ease, color 0.16s ease, border-color 0.16s ease;
}

.folder-row:hover {
  background: var(--surface-2);
  color: var(--text);
}

.folder-row.active {
  background: var(--accent-soft);
  border-color: rgba(99, 102, 241, 0.28);
  color: var(--text);
}

.folder-row.root {
  font-weight: 600;
}

.folder-chevron {
  width: 14px;
  flex: none;
  color: var(--text-muted);
}

.folder-chevron svg {
  width: 13px;
  height: 13px;
}

.folder-row-icon {
  width: 22px;
  height: 22px;
  flex: none;
  display: grid;
  place-items: center;
  color: var(--accent-2);
}

.folder-row-icon svg {
  width: 16px;
  height: 16px;
}

.folder-row-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-row-count {
  flex: none;
  min-width: 22px;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: 11px;
  text-align: center;
}

.folder-row-actions {
  display: none;
  align-items: center;
  gap: 2px;
  flex: none;
}

.folder-row:hover .folder-row-actions {
  display: flex;
}

.folder-row-op,
.site-op {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--text-muted);
  transition: all 0.15s ease;
}

.folder-row-op:hover,
.site-op:hover {
  color: var(--text);
  background: var(--surface-2);
}

.folder-row-op.danger:hover,
.site-op.danger:hover {
  color: var(--danger);
  background: rgba(248, 113, 113, 0.12);
}

.folder-row-op svg,
.site-op svg {
  width: 14px;
  height: 14px;
}

.sites-content {
  min-width: 0;
  overflow-y: auto;
  padding: 26px 28px 44px;
}

.sites-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.sites-toolbar h1 {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.sites-toolbar p {
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 13px;
}

.primary-btn,
.ghost-btn {
  height: 38px;
  padding: 0 15px;
  border-radius: 11px;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  transition: transform 0.16s ease, filter 0.16s ease, background 0.16s ease,
    border-color 0.16s ease, color 0.16s ease;
}

.primary-btn {
  color: #fff;
  background: var(--accent-grad);
  box-shadow: 0 10px 24px -12px var(--accent-ring);
}

.primary-btn:hover {
  transform: translateY(-1px);
  filter: brightness(1.06);
}

.primary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
}

.primary-btn svg {
  width: 16px;
  height: 16px;
}

.ghost-btn {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
}

.ghost-btn:hover {
  color: var(--text);
  border-color: var(--border-strong);
  background: var(--surface-2);
}

.sites-error {
  margin-bottom: 14px;
  padding: 10px 13px;
  border-radius: 11px;
  border: 1px solid rgba(248, 113, 113, 0.26);
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger);
  font-size: 13px;
}

.sites-loading {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 60px 0;
}

.sites-loading span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  animation: site-bounce 1s infinite ease-in-out;
}

.sites-loading span:nth-child(2) {
  animation-delay: 0.14s;
}

.sites-loading span:nth-child(3) {
  animation-delay: 0.28s;
}

@keyframes site-bounce {
  0%,
  100% {
    opacity: 0.35;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-5px);
  }
}

.sites-empty {
  min-height: 360px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px 24px;
}

.sites-empty-icon {
  width: 76px;
  height: 76px;
  border-radius: 24px;
  background: var(--accent-grad);
  display: grid;
  place-items: center;
  color: #fff;
  margin-bottom: 18px;
  box-shadow: 0 18px 40px -14px var(--accent-ring);
}

.sites-empty-icon svg {
  width: 34px;
  height: 34px;
}

.sites-empty h3 {
  font-size: 19px;
  font-weight: 680;
}

.sites-empty p {
  margin: 6px 0 22px;
  color: var(--text-muted);
  font-size: 13.5px;
}

.sites-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 14px;
}

.site-card {
  min-width: 0;
  padding: 16px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background: var(--surface);
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
  animation: site-card-in 0.28s ease both;
}

.site-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
  background: var(--surface-2);
}

@keyframes site-card-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.site-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.site-favicon {
  width: 42px;
  height: 42px;
  flex: none;
  border-radius: 13px;
  overflow: hidden;
  display: grid;
  place-items: center;
  background: var(--surface-2);
  box-shadow: inset 0 0 0 1px var(--border);
}

.site-favicon img {
  width: 24px;
  height: 24px;
  object-fit: contain;
}

.site-favicon span {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 18px;
  font-weight: 700;
}

.site-card-actions {
  display: flex;
  gap: 3px;
  opacity: 0;
  transform: translateY(-2px);
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.site-card:hover .site-card-actions {
  opacity: 1;
  transform: translateY(0);
}

.site-name {
  display: block;
  margin-top: 14px;
  color: var(--text);
  font-size: 15px;
  font-weight: 650;
  text-decoration: none;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.site-name:hover {
  color: var(--accent-2);
}

.site-domain {
  display: block;
  margin-top: 5px;
  color: var(--text-muted);
  font-size: 12px;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.site-domain:hover {
  color: var(--accent-2);
}

.site-desc {
  margin-top: 11px;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.site-foot {
  margin-top: 13px;
  display: flex;
  align-items: center;
}

.site-folder {
  max-width: 100%;
  padding: 4px 9px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

[data-theme='light'] .site-folder {
  color: var(--accent);
}

.site-folder.muted {
  background: var(--surface-2);
  color: var(--text-muted);
}

/* 弹窗 */
.sites-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  animation: fade-in 0.2s ease both;
}

.sites-modal {
  width: 100%;
  max-width: 440px;
  padding: 22px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: var(--surface-solid);
  box-shadow: var(--shadow);
  animation: modal-in 0.22s ease both;
}

@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes modal-in {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.sites-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.sites-modal-head h2 {
  font-size: 18px;
  font-weight: 680;
}

.modal-close {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  color: var(--text-muted);
  transition: all 0.16s ease;
}

.modal-close:hover {
  color: var(--text);
  background: var(--surface-2);
}

.modal-close svg {
  width: 16px;
  height: 16px;
}

.modal-field {
  display: block;
  margin-bottom: 14px;
}

.modal-field span {
  display: block;
  margin-bottom: 7px;
  color: var(--text-2);
  font-size: 12.5px;
}

.modal-field input,
.modal-field select,
.modal-field textarea {
  width: 100%;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  outline: none;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.modal-field textarea {
  resize: vertical;
  min-height: 74px;
  line-height: 1.5;
}

.modal-field input:focus,
.modal-field select:focus,
.modal-field textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

@media (max-width: 900px) {
  .sites-layout {
    grid-template-columns: 230px minmax(0, 1fr);
  }
  .sites-content {
    padding: 22px 20px 36px;
  }
}

@media (max-width: 720px) {
  .sites-layout {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .sites-sidebar {
    flex: none;
    overflow: visible;
    padding: 12px 12px 10px;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
  .sites-sidebar-head {
    padding: 0 4px 8px;
  }
  .sites-search {
    margin: 0 2px 10px;
  }
  .folder-tree {
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 4px;
  }
  .folder-tree-empty {
    white-space: nowrap;
    padding: 10px;
  }
  .folder-tree-sep {
    display: none;
  }
  .folder-row {
    flex: none;
    min-width: max-content;
  }
  .folder-row-actions {
    display: flex;
  }
  .sites-content {
    flex: 1;
    overflow-y: auto;
    padding: 18px 14px 32px;
  }
  .sites-toolbar h1 {
    font-size: 21px;
  }
  .sites-grid {
    grid-template-columns: 1fr;
  }
  .site-card-actions {
    opacity: 1;
    transform: none;
  }
}
</style>
