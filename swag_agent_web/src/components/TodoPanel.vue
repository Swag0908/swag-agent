<script setup>
import { ref, computed, watch } from 'vue'
import { getToday, createTodo, completeTodo, deferTodo, deleteTodo } from '../api/todo'

const props = defineProps({
  open: { type: Boolean, default: false }
})
const emit = defineEmits(['close'])

const items = ref([])
const loading = ref(false)
const error = ref('')

const newTitle = ref('')
const newNote = ref('')
const adding = ref(false)

const doneCount = computed(() => items.value.filter((i) => i.status === 'DONE').length)

async function refresh() {
  loading.value = true
  try {
    items.value = await getToday()
    error.value = ''
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

async function toggle(item) {
  if (item.status === 'DONE') return
  error.value = ''
  try {
    await completeTodo(item.id)
    await refresh()
  } catch (e) {
    error.value = e?.message
  }
}

async function deferTomorrow(item) {
  error.value = ''
  try {
    await deferTodo(item.id, null)
    await refresh()
  } catch (e) {
    error.value = e?.message
  }
}

async function remove(item) {
  error.value = ''
  try {
    await deleteTodo(item.id)
    await refresh()
  } catch (e) {
    error.value = e?.message
  }
}

async function add() {
  const title = newTitle.value.trim()
  if (!title) return
  adding.value = true
  error.value = ''
  try {
    await createTodo({ title, note: newNote.value.trim() || undefined })
    newTitle.value = ''
    newNote.value = ''
    await refresh()
  } catch (e) {
    error.value = e?.message
  } finally {
    adding.value = false
  }
}

defineExpose({ refresh })
</script>

<template>
  <transition name="fade">
    <div v-if="open" class="todo-mask" @click="emit('close')"></div>
  </transition>

  <aside class="todo-drawer" :class="{ open }">
    <header class="todo-head">
      <div>
        <h2>今日待办</h2>
        <p class="todo-sub">{{ doneCount }}/{{ items.length }} 已完成</p>
      </div>
      <button class="icon-btn" title="关闭" @click="emit('close')">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </header>

    <div class="todo-body">
      <p v-if="error" class="todo-error">{{ error }}</p>

      <div v-if="loading" class="todo-empty">加载中…</div>
      <div v-else-if="!items.length" class="todo-empty">今天还没有待办，去聊天里安排一下吧。</div>

      <ul v-else class="todo-list">
        <li v-for="item in items" :key="item.id" class="todo-item" :class="{ done: item.status === 'DONE' }">
          <button class="todo-check" :title="item.status === 'DONE' ? '已完成' : '标记完成'" @click="toggle(item)">
            <svg v-if="item.status === 'DONE'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 6 9 17l-5-5" />
            </svg>
          </button>

          <div class="todo-main">
            <div class="todo-title">{{ item.title }}</div>
            <div v-if="item.note" class="todo-note">{{ item.note }}</div>
            <div class="todo-meta">
              <span v-if="item.dueTime" class="todo-time">截止 {{ item.dueTime }}</span>
              <span class="todo-src">{{ item.source === 'MANUAL' ? '手动' : '聊天' }}</span>
            </div>
          </div>

          <div class="todo-ops">
            <button v-if="item.status !== 'DONE'" class="todo-op" title="延期到明天" @click="deferTomorrow(item)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3 2" />
              </svg>
            </button>
            <button class="todo-op danger" title="删除" @click="remove(item)">
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

    <footer class="todo-add">
      <input v-model="newTitle" class="todo-input" placeholder="新增待办，回车添加" @keydown.enter.prevent="add" />
      <input v-model="newNote" class="todo-input note" placeholder="备注（可选）" @keydown.enter.prevent="add" />
      <button class="auth-submit" :disabled="adding || !newTitle.trim()" @click="add">
        {{ adding ? '…' : '添加' }}
      </button>
    </footer>
  </aside>
</template>
