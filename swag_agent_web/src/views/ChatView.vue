<script setup>
import { ref, watch, nextTick, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useChat } from '../composables/useChat'
import ChatMessage from '../components/ChatMessage.vue'
import ChatInput from '../components/ChatInput.vue'
import EmptyState from '../components/EmptyState.vue'
import ModelSelector from '../components/ModelSelector.vue'
import TodoPanel from '../components/TodoPanel.vue'
import { currentTheme, applyTheme } from '../theme'
import { clearAuth, getUser } from '../auth'
import { logout as logoutApi } from '../api/auth'

// id 与后端 SelectModelTool 保持一致：1 = V4 Flash（默认），2 = V4 Pro
const MODELS = [
  { id: 1, name: 'DeepSeek V4 Flash', desc: '快速响应，适合日常对话' },
  { id: 2, name: 'DeepSeek V4 Pro', desc: '深度推理，适合复杂任务' }
]

const router = useRouter()
const { messages, sending, modelId, send, stop, clear } = useChat()

const user = getUser()

/* ---------- 主题切换 ---------- */
const theme = ref(currentTheme())
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  applyTheme(theme.value)
}

/* ---------- 待办面板 ---------- */
const panelOpen = ref(false)
const panelRef = ref(null)

/* ---------- 手机端「更多」菜单 ---------- */
const moreOpen = ref(false)
const moreRoot = ref(null)

function toggleMore() {
  moreOpen.value = !moreOpen.value
}

function onDocClick(e) {
  if (moreRoot.value && !moreRoot.value.contains(e.target)) moreOpen.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))

function selectMobileModel(m) {
  modelId.value = m.id
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

function clearAndClose() {
  clear()
  moreOpen.value = false
}

/* ---------- 退出登录 ---------- */
async function logout() {
  try {
    await logoutApi()
  } catch {
    /* 忽略，本地登出优先 */
  }
  clearAuth()
  router.push({ name: 'login' })
}

/* ---------- 滚动控制 ---------- */
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

/* ---------- 发送 ---------- */
async function handleSend(text) {
  atBottom.value = true
  scrollToBottom(false)
  await send(text)
  // 聊天里可能新增/完成了待办，同步刷新侧栏
  panelRef.value?.refresh()
}
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <div class="brand-logo">
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path
              d="M12 2.5l2.1 6.4 6.4 2.1-6.4 2.1L12 19.5l-2.1-6.4L3.5 11l6.4-2.1L12 2.5z"
            />
            <path
              d="M19 3l.7 2.3L22 6l-2.3.7L19 9l-.7-2.3L16 6l2.3-.7L19 3z"
              opacity=".7"
            />
          </svg>
        </div>
        <div class="brand-text">
          <span class="brand-name">SWAG Agent</span>
          <span class="brand-tag">{{ user?.displayName || user?.username || '未登录' }}</span>
        </div>
      </div>

      <div class="topbar-actions">
        <button class="nav-btn desktop-only" @click="router.push({ name: 'sites' })">常用网站</button>
        <button class="nav-btn desktop-only" @click="router.push({ name: 'stats' })">统计</button>

        <ModelSelector class="desktop-only" :model-id="modelId" :models="MODELS" @select="selectModel" />

        <button
          class="icon-btn"
          :class="{ active: panelOpen }"
          title="今日待办"
          @click="panelOpen = !panelOpen"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M9 6h11" />
            <path d="M9 12h11" />
            <path d="M9 18h11" />
            <path d="m3 6 1.5 1.5L7 5" />
            <path d="m3 12 1.5 1.5L7 11" />
            <path d="m3 18 1.5 1.5L7 17" />
          </svg>
        </button>

        <button
          class="icon-btn desktop-only"
          title="清空对话"
          :disabled="!messages.length"
          @click="clear"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M3 6h18" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
            <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>

        <button class="icon-btn" title="切换主题" @click="toggleTheme">
          <svg
            v-if="theme === 'dark'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
          </svg>
          <svg
            v-else
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </button>

        <button class="icon-btn desktop-only" title="退出登录" @click="logout">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <path d="m16 17 5-5-5-5" />
            <path d="M21 12H9" />
          </svg>
        </button>

        <!-- 手机端「更多」菜单 -->
        <div ref="moreRoot" class="more-root">
          <button
            class="icon-btn mobile-more"
            :class="{ active: moreOpen }"
            title="更多"
            @click="toggleMore"
          >
            <svg
              viewBox="0 0 24 24"
              fill="currentColor"
            >
              <circle cx="12" cy="5" r="1.8" />
              <circle cx="12" cy="12" r="1.8" />
              <circle cx="12" cy="19" r="1.8" />
            </svg>
          </button>

          <div v-if="moreOpen" class="more-menu">
            <div class="more-label">模型</div>
            <button
              v-for="m in MODELS"
              :key="m.id"
              type="button"
              class="model-item"
              :class="{ active: m.id === modelId }"
              @click="selectMobileModel(m)"
            >
              <div class="model-item-main">
                <div class="model-item-name">{{ m.name }}</div>
                <div class="model-item-desc">{{ m.desc }}</div>
              </div>
              <span v-if="m.id === modelId" class="model-item-check">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2.4"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M20 6 9 17l-5-5" />
                </svg>
              </span>
            </button>

            <div class="more-sep"></div>

            <button type="button" class="more-action" @click="goSites">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <circle cx="12" cy="12" r="9" />
                <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
              </svg>
              常用网站
            </button>

            <button type="button" class="more-action" @click="goStats">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M3 3v18h18" />
                <path d="M8 17v-5M13 17V7M18 17v-8" />
              </svg>
              统计
            </button>

            <button type="button" class="more-action" :disabled="!messages.length" @click="clearAndClose">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M3 6h18" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
              清空对话
            </button>

            <button type="button" class="more-action danger" @click="logout">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <path d="m16 17 5-5-5-5" />
                <path d="M21 12H9" />
              </svg>
              退出登录
            </button>
          </div>
        </div>
      </div>
    </header>

    <main class="chat" ref="chatEl" @scroll="onScroll">
      <EmptyState v-if="!messages.length" @select="handleSend" />
      <div v-else class="messages">
        <ChatMessage v-for="m in messages" :key="m.id" :message="m" />
      </div>
    </main>

    <button
      v-if="!atBottom && messages.length"
      class="scroll-fab"
      title="回到底部"
      @click="scrollToBottom(true)"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M12 5v14M19 12l-7 7-7-7" />
      </svg>
    </button>

    <footer class="composer">
      <div class="composer-inner">
        <ChatInput :sending="sending" @send="handleSend" @stop="stop" />
        <p class="composer-hint">
          直接告诉我要做什么，例如「下午3点开会，写周报，买牛奶」；做完再说「xxx 做完了」。
        </p>
      </div>
    </footer>

    <TodoPanel ref="panelRef" :open="panelOpen" @close="panelOpen = false" />
  </div>
</template>
