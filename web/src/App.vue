<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import { useChat } from './composables/useChat'
import ChatMessage from './components/ChatMessage.vue'
import ChatInput from './components/ChatInput.vue'
import EmptyState from './components/EmptyState.vue'
import ModelSelector from './components/ModelSelector.vue'

const MODELS = [{ id: 1, name: 'DeepSeek V4 Pro', desc: '高性能推理模型' }]

const { messages, sending, modelId, send, stop, clear } = useChat()

/* ---------- 主题切换 ---------- */
const theme = ref(localStorage.getItem('swag-theme') || 'dark')

function applyTheme() {
  document.documentElement.setAttribute('data-theme', theme.value)
  localStorage.setItem('swag-theme', theme.value)
}
applyTheme()

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  applyTheme()
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

// 消息数变化 / 流式内容增长时，若用户在底部则自动跟随
const lastContent = computed(() => {
  const last = messages[messages.length - 1]
  return last ? last.content : ''
})

watch(() => messages.length, () => {
  if (atBottom.value) scrollToBottom(false)
})
watch(lastContent, () => {
  if (atBottom.value) scrollToBottom(false)
})

/* ---------- 发送 ---------- */
async function handleSend(text) {
  atBottom.value = true
  scrollToBottom(false)
  await send(text)
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
          <span class="brand-tag">Powered by DeepSeek</span>
        </div>
      </div>

      <div class="topbar-actions">
        <ModelSelector :model-id="modelId" :models="MODELS" @select="modelId = $event" />

        <button
          class="icon-btn"
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
        <p class="composer-hint">Enter 发送 · Shift + Enter 换行 · 测试版暂无多轮上下文记忆</p>
      </div>
    </footer>
  </div>
</template>
