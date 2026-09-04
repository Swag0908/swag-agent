<script setup>
import { ref, watch, nextTick, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useChat, ACTIVE_CONVERSATION_KEY } from '../composables/useChat'
import ChatMessage from '../components/ChatMessage.vue'
import ChatInput from '../components/ChatInput.vue'
import EmptyState from '../components/EmptyState.vue'
import ModelSelector from '../components/ModelSelector.vue'
import TodoPanel from '../components/TodoPanel.vue'
import ConversationList from '../components/ConversationList.vue'
import UserMemoryPanel from '../components/UserMemoryPanel.vue'
import { currentTheme, applyTheme } from '../theme'
import { clearAuth, getUser } from '../auth'
import { logout as logoutApi } from '../api/auth'

const MODELS = [
  { id: 1, name: 'DeepSeek V4 Flash', desc: '快速响应，适合日常对话' },
  { id: 2, name: 'DeepSeek V4 Pro', desc: '深度推理，适合复杂任务' }
]

const router = useRouter()
const {
  messages,
  sending,
  modelId,
  conversations,
  conversationId,
  conversationTitle,
  loadingHistory,
  send,
  stop,
  newConversation,
  openConversation,
  refreshConversations
} = useChat()
const user = getUser()

const theme = ref(currentTheme())
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  applyTheme(theme.value)
}

const panelOpen = ref(false)
const panelRef = ref(null)
const memoryOpen = ref(false)
const histOpen = ref(false)
const moreOpen = ref(false)
const moreRoot = ref(null)

function toggleMore() {
  moreOpen.value = !moreOpen.value
}

function onDocClick(event) {
  if (moreRoot.value && !moreRoot.value.contains(event.target)) moreOpen.value = false
}

onMounted(async () => {
  document.addEventListener('click', onDocClick)
  await refreshConversations()
  // 优先恢复上次打开的会话；其次自动打开最近会话，避免每次都要重新输入相同问题
  if (conversationId.value == null) {
    const saved = Number(localStorage.getItem(ACTIVE_CONVERSATION_KEY))
    const target =
      conversations.value.find((c) => Number(c.id) === saved) ||
      conversations.value[0] ||
      null
    if (target) await openConversation(target)
  }
})
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))

function selectMobileModel(model) {
  modelId.value = model.id
  moreOpen.value = false
}

function selectModel(id) {
  modelId.value = id
}

function goStats() {
  moreOpen.value = false
  router.push({ name: 'stats' })
}

function goSites() {
  moreOpen.value = false
  router.push({ name: 'sites' })
}

function goNotes() {
  moreOpen.value = false
  router.push({ name: 'notes' })
}

async function startNewChat() {
  moreOpen.value = false
  histOpen.value = false
  newConversation()
}

async function onSelectConversation(conv) {
  histOpen.value = false
  await openConversation(conv)
}

async function logout() {
  try {
    await logoutApi()
  } catch {
    // 本地登出优先
  }
  clearAuth()
  router.push({ name: 'login' })
}

const chatEl = ref(null)
const atBottom = ref(true)

function onScroll() {
  const el = chatEl.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

async function scrollToBottom(smooth = true) {
  await nextTick()
  const el = chatEl.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
}

const lastContent = computed(() => {
  const last = messages[messages.length - 1]
  return last ? last.content : ''
})

watch(
  () => messages.length,
  () => {
    if (atBottom.value) scrollToBottom(false)
  }
)
watch(lastContent, () => {
  if (atBottom.value) scrollToBottom(false)
})

const currentTitle = computed(() => {
  if (conversationId.value != null) {
    return conversationTitle.value || (messages.length ? '当前会话' : '新对话')
  }
  return messages.length ? '当前会话' : '新任务'
})

async function handleSend(text) {
  atBottom.value = true
  scrollToBottom(false)
  await send(text)
  panelRef.value?.refresh()
}
</script>

<template>
  <div class="app chat-app">
    <aside class="app-sidebar desktop-shell">
      <div class="sidebar-brand">
        <div class="sidebar-mark">
          <img src="/brand/cowhorse-glyph-256.png" alt="Cowhourse Legend" />
        </div>
        <div class="sidebar-wordmark">
          <strong>COWHOURSE</strong>
          <span>LEGEND / 牛马传奇</span>
        </div>
      </div>

      <button class="new-session" type="button" @click="startNewChat">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M12 5v14M5 12h14" />
        </svg>
        <span>新建会话</span>
      </button>

      <div class="sidebar-history">
        <div class="sidebar-label">历史会话</div>
        <div class="history-scroll">
          <ConversationList
            :conversations="conversations"
            :active-id="conversationId"
            empty-text="暂无历史会话"
            @select="onSelectConversation"
          />
        </div>
      </div>

      <div class="sidebar-section nav-dock">
        <div class="sidebar-label">WORKSPACE</div>
        <nav class="sidebar-nav" aria-label="主导航">
          <button class="sidebar-link active" type="button">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M5 5h14v11H9l-4 4V5Z" />
            </svg>
            <span>智能对话</span>
            <i></i>
          </button>
          <button class="sidebar-link" type="button" @click="panelOpen = true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M8 6h12M8 12h12M8 18h12M3.5 6h.01M3.5 12h.01M3.5 18h.01" />
            </svg>
            <span>今日待办</span>
          </button>
          <button class="sidebar-link" type="button" @click="memoryOpen = true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M9 4h6v2H9V4Zm-2 3h10v2H7V7Zm-2 3h14v2H5v-2Zm4 3h6v7l-3-2-3 2v-7Z" />
            </svg>
            <span>我的记忆</span>
          </button>
          <button class="sidebar-link" type="button" @click="goSites">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="8.5" />
              <path d="M3.5 12h17M12 3.5c2.2 2.4 3.3 5.2 3.3 8.5S14.2 18.1 12 20.5C9.8 18.1 8.7 15.3 8.7 12S9.8 5.9 12 3.5Z" />
            </svg>
            <span>常用网站</span>
          </button>
          <button class="sidebar-link" type="button" @click="goNotes">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M6 3h9l4 4v14H6V3Z" />
              <path d="M15 3v4h4M9 11h7M9 15h7" />
            </svg>
            <span>Markdown 笔记</span>
          </button>
          <button class="sidebar-link" type="button" @click="goStats">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M4 19V9M10 19V5M16 19v-7M22 19H2" />
            </svg>
            <span>效率统计</span>
          </button>
        </nav>
      </div>

      <div class="system-card">
        <div class="system-card-head">
          <span class="status-pulse"></span>
          SYSTEM ONLINE
        </div>
        <p>DeepSeek runtime 已连接</p>
        <div class="system-meter"><span></span></div>
      </div>

      <div class="sidebar-user">
        <div class="user-avatar">{{ (user?.displayName || user?.username || 'U').slice(0, 1).toUpperCase() }}</div>
        <div class="user-copy">
          <strong>{{ user?.displayName || user?.username || '未登录' }}</strong>
          <span>LEGEND MEMBER</span>
        </div>
        <button type="button" title="退出登录" @click="logout">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M9 5H5v14h4M14 8l4 4-4 4M18 12H8" />
          </svg>
        </button>
      </div>
    </aside>

    <section class="workspace">
      <header class="workspace-bar">
        <div class="mobile-brand">
          <img src="/brand/cowhorse-glyph-256.png" alt="" />
          <strong>COWHOURSE</strong>
        </div>
        <div class="workspace-title desktop-shell">
          <span>COWHOURSE LEGEND</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="m9 18 6-6-6-6" /></svg>
          <strong>{{ currentTitle }}</strong>
        </div>
        <div class="workspace-actions">
          <button class="work-icon mobile-shell" type="button" title="历史会话" @click="histOpen = !histOpen">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" />
            </svg>
          </button>
          <div class="preview-badge desktop-shell"><span></span>LIVE</div>
          <ModelSelector class="desktop-shell" :model-id="modelId" :models="MODELS" @select="selectModel" />
          <button class="work-icon" type="button" title="切换主题" @click="toggleTheme">
            <svg v-if="theme === 'dark'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="3.5" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M20.5 14.1A8.5 8.5 0 0 1 9.9 3.5a8.5 8.5 0 1 0 10.6 10.6Z" />
            </svg>
          </button>

          <div ref="moreRoot" class="more-root mobile-shell">
            <button class="work-icon" type="button" title="更多" @click="toggleMore">
              <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="12" cy="19" r="1.6" /></svg>
            </button>
            <div v-if="moreOpen" class="more-menu">
              <div class="more-label">模型</div>
              <button
                v-for="model in MODELS"
                :key="model.id"
                type="button"
                class="model-item"
                :class="{ active: model.id === modelId }"
                @click="selectMobileModel(model)"
              >
                <div class="model-item-main">
                  <div class="model-item-name">{{ model.name }}</div>
                  <div class="model-item-desc">{{ model.desc }}</div>
                </div>
              </button>
              <div class="more-sep"></div>
              <button type="button" class="more-action" @click="startNewChat">新建会话</button>
              <button type="button" class="more-action" @click="histOpen = true; moreOpen = false">历史会话</button>
              <button type="button" class="more-action" @click="memoryOpen = true; moreOpen = false">我的记忆</button>
              <button type="button" class="more-action" @click="panelOpen = true; moreOpen = false">今日待办</button>
              <button type="button" class="more-action" @click="goSites">常用网站</button>
              <button type="button" class="more-action" @click="goNotes">Markdown 笔记</button>
              <button type="button" class="more-action" @click="goStats">效率统计</button>
              <button type="button" class="more-action danger" @click="logout">退出登录</button>
            </div>
          </div>
        </div>
      </header>

      <main ref="chatEl" class="chat" @scroll="onScroll">
        <div v-if="loadingHistory" class="history-loading">正在载入历史对话…</div>
        <EmptyState v-else-if="!messages.length" @select="handleSend" />
        <div v-else class="messages">
          <ChatMessage v-for="message in messages" :key="message.id" :message="message" />
        </div>
      </main>

      <button
        v-if="!atBottom && messages.length"
        class="scroll-fab"
        title="回到底部"
        @click="scrollToBottom(true)"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 5v14M19 12l-7 7-7-7" /></svg>
      </button>

      <footer class="composer">
        <div class="composer-inner">
          <ChatInput :sending="sending" @send="handleSend" @stop="stop" />
          <p class="composer-hint">Cowhourse Legend 可能会犯错。重要信息请再次核对。</p>
        </div>
      </footer>
    </section>

    <!-- 移动端历史会话抽屉 -->
    <transition name="fade">
      <div v-if="histOpen" class="hist-mask" @click="histOpen = false"></div>
    </transition>
    <aside class="hist-drawer" :class="{ open: histOpen }">
      <header class="hist-head">
        <div>
          <h2>历史会话</h2>
          <p class="hist-sub">{{ conversations.length }} 个会话</p>
        </div>
        <button class="icon-btn" title="关闭" @click="histOpen = false">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </header>
      <div class="hist-body">
        <ConversationList
          :conversations="conversations"
          :active-id="conversationId"
          empty-text="还没有历史会话"
          @select="onSelectConversation"
        />
      </div>
      <footer class="hist-foot">
        <button class="hist-new" type="button" @click="startNewChat">＋ 新建会话</button>
      </footer>
    </aside>

    <TodoPanel ref="panelRef" :open="panelOpen" @close="panelOpen = false" />
    <UserMemoryPanel :open="memoryOpen" @close="memoryOpen = false" />
  </div>
</template>
