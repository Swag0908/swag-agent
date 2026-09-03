<script setup>
import { ref, watch } from 'vue'
import { getUserMemory, setUserMemoryEnabled, deleteUserMemory } from '../api/userMemory'

const props = defineProps({
  open: { type: Boolean, default: false }
})
const emit = defineEmits(['close'])

const enabled = ref(true)
const items = ref([])
const loading = ref(false)
const error = ref('')
const toggling = ref(false)

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const data = await getUserMemory()
    enabled.value = !!data.enabled
    items.value = Array.isArray(data.items) ? data.items : []
  } catch (e) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (v) => {
    if (v) refresh()
  }
)

async function toggleEnabled() {
  toggling.value = true
  error.value = ''
  try {
    const next = !enabled.value
    await setUserMemoryEnabled(next)
    enabled.value = next
  } catch (e) {
    error.value = e?.message
  } finally {
    toggling.value = false
  }
}

async function remove(item) {
  error.value = ''
  try {
    await deleteUserMemory(item.id)
    await refresh()
  } catch (e) {
    error.value = e?.message
  }
}

function fmtTime(ms) {
  if (!ms) return ''
  const d = new Date(ms)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  if (sameDay) return `今天 ${hh}:${mm}`
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
</script>

<template>
  <transition name="fade">
    <div v-if="open" class="todo-mask" @click="emit('close')"></div>
  </transition>

  <aside class="todo-drawer memory-drawer" :class="{ open }">
    <header class="todo-head">
      <div>
        <h2>我的记忆</h2>
        <p class="todo-sub">你让助手长期记住的偏好与事实，跨会话生效</p>
      </div>
      <button class="icon-btn" title="关闭" @click="emit('close')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </header>

    <div class="memory-body">
      <p v-if="error" class="todo-error">{{ error }}</p>

      <div class="memory-toggle">
        <div>
          <strong>长期记忆</strong>
          <span>开启后，助手会在对话时参考这些记忆</span>
        </div>
        <button
          type="button"
          class="mem-switch"
          :class="{ on: enabled }"
          :disabled="toggling"
          role="switch"
          :aria-checked="enabled"
          @click="toggleEnabled"
        >
          <span></span>
        </button>
      </div>

      <div v-if="loading" class="todo-empty">加载中…</div>
      <div v-else-if="!items.length" class="todo-empty">
        还没有记忆。<br />在对话里告诉助手「记住…」，就会出现在这里。
      </div>

      <ul v-else class="memory-list">
        <li v-for="item in items" :key="item.id" class="memory-item">
          <div class="memory-content">{{ item.content }}</div>
          <div class="memory-meta">
            <span>{{ fmtTime(item.createdAtMs) }}</span>
            <button class="todo-op danger" title="删除这条记忆" @click="remove(item)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 6h18" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          </div>
        </li>
      </ul>
    </div>
  </aside>
</template>
