<script setup>
import { computed, ref, watch } from 'vue'
import {
  completeTodo,
  createTodo,
  deferTodo,
  deleteTodo,
  getStats,
  getTodos,
  updateTodo
} from '../api/todo'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close'])

const weekDays = ['一', '二', '三', '四', '五', '六', '日']
const now = new Date()
const today = dateKey(now)
const monthCursor = ref(new Date(now.getFullYear(), now.getMonth(), 1))
const selectedDate = ref(today)
const items = ref([])
const stats = ref([])
const loading = ref(false)
const error = ref('')
const adding = ref(false)
const saving = ref(false)
const newTitle = ref('')
const newNote = ref('')
const newDueDate = ref(today)
const newDueTime = ref('')
const dialog = ref(null)
const editForm = ref({})

function dateKey(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function fromKey(key) {
  const [year, month, day] = key.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function plusDays(key, amount) {
  const date = fromKey(key)
  date.setDate(date.getDate() + amount)
  return dateKey(date)
}

const calendarDays = computed(() => {
  const year = monthCursor.value.getFullYear()
  const month = monthCursor.value.getMonth()
  const firstDay = new Date(year, month, 1)
  const mondayOffset = (firstDay.getDay() + 6) % 7
  const start = new Date(year, month, 1 - mondayOffset)
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start)
    date.setDate(start.getDate() + index)
    return { key: dateKey(date), day: date.getDate(), outside: date.getMonth() !== month }
  })
})

const monthLabel = computed(() =>
  `${monthCursor.value.getFullYear()} 年 ${monthCursor.value.getMonth() + 1} 月`
)
const gridFrom = computed(() => calendarDays.value[0].key)
const gridTo = computed(() => calendarDays.value[calendarDays.value.length - 1].key)
const selectedItems = computed(() => items.value.filter((item) => item.dueDate === selectedDate.value))
const selectedDoneCount = computed(
  () => selectedItems.value.filter((item) => item.status === 'DONE').length
)
const selectedDateLabel = computed(() => {
  const date = fromKey(selectedDate.value)
  const suffix = selectedDate.value === today ? ' · 今天' : ''
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日${suffix}`
})
const statByDate = computed(() => new Map(stats.value.map((stat) => [stat.statDate, stat])))

function dayState(key) {
  const stat = statByDate.value.get(key)
  const currentItems = items.value.filter((item) => item.dueDate === key)
  const settled = stat
    ? stat.completedCount + stat.pendingCount + stat.deferredCount
    : currentItems.length
  let completion = null
  if (key < today && settled > 0) {
    const completed = stat?.completedCount
      ?? currentItems.filter((item) => item.status === 'DONE').length
    completion = completed === settled ? 'complete' : 'incomplete'
  }
  return { count: currentItems.length || settled, completion }
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [monthItems, monthStats] = await Promise.all([
      getTodos(gridFrom.value, gridTo.value),
      getStats(gridFrom.value, gridTo.value)
    ])
    items.value = monthItems
    stats.value = monthStats
  } catch (e) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

watch(() => props.open, (isOpen) => {
  if (isOpen) refresh()
})

async function moveMonth(amount) {
  const current = monthCursor.value
  monthCursor.value = new Date(current.getFullYear(), current.getMonth() + amount, 1)
  selectedDate.value = dateKey(monthCursor.value)
  newDueDate.value = selectedDate.value
  await refresh()
}

async function selectDay(day) {
  selectedDate.value = day.key
  newDueDate.value = day.key
  if (day.outside) {
    const date = fromKey(day.key)
    monthCursor.value = new Date(date.getFullYear(), date.getMonth(), 1)
    await refresh()
  }
}

async function toggle(item) {
  if (item.status === 'DONE') return
  await mutate(() => completeTodo(item.id))
}

function openEdit(item) {
  editForm.value = {
    id: item.id,
    title: item.title,
    note: item.note || '',
    dueDate: item.dueDate,
    dueTime: item.dueTime ? item.dueTime.slice(0, 5) : ''
  }
  dialog.value = 'edit'
}

function openDefer(item) {
  editForm.value = {
    id: item.id,
    title: item.title,
    currentDate: item.dueDate,
    dueDate: plusDays(item.dueDate, 1)
  }
  dialog.value = 'defer'
}

async function saveEdit() {
  const form = editForm.value
  if (!form.title?.trim() || !form.dueDate) return
  saving.value = true
  try {
    await updateTodo(form.id, {
      title: form.title.trim(),
      note: form.note.trim() || null,
      dueDate: form.dueDate,
      dueTime: form.dueTime || null
    })
    dialog.value = null
    await showDate(form.dueDate)
  } catch (e) {
    error.value = e?.message || '修改失败'
  } finally {
    saving.value = false
  }
}

async function saveDefer() {
  const form = editForm.value
  if (!form.dueDate) return
  saving.value = true
  try {
    await deferTodo(form.id, form.dueDate)
    dialog.value = null
    await showDate(form.dueDate)
  } catch (e) {
    error.value = e?.message || '延期失败'
  } finally {
    saving.value = false
  }
}

async function showDate(key) {
  const date = fromKey(key)
  selectedDate.value = key
  newDueDate.value = key
  monthCursor.value = new Date(date.getFullYear(), date.getMonth(), 1)
  await refresh()
}

async function remove(item) {
  await mutate(() => deleteTodo(item.id))
}

async function mutate(operation) {
  error.value = ''
  try {
    await operation()
    await refresh()
  } catch (e) {
    error.value = e?.message || '操作失败'
  }
}

async function add() {
  const title = newTitle.value.trim()
  if (!title || !newDueDate.value) return
  adding.value = true
  error.value = ''
  try {
    await createTodo({
      title,
      note: newNote.value.trim() || null,
      dueDate: newDueDate.value,
      dueTime: newDueTime.value || null
    })
    newTitle.value = ''
    newNote.value = ''
    newDueTime.value = ''
    await showDate(newDueDate.value)
  } catch (e) {
    error.value = e?.message || '添加失败'
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

  <aside class="todo-drawer todo-calendar-drawer" :class="{ open }">
    <header class="todo-head">
      <div>
        <h2>待办日历</h2>
        <p class="todo-sub">选择日期查看待办，过去日期的颜色表示完成情况</p>
      </div>
      <button class="icon-btn" title="关闭" @click="emit('close')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </header>

    <div class="todo-calendar-layout">
      <section class="todo-calendar-pane">
        <div class="todo-month-nav">
          <button class="todo-month-btn" title="上个月" @click="moveMonth(-1)">‹</button>
          <strong>{{ monthLabel }}</strong>
          <button class="todo-month-btn" title="下个月" @click="moveMonth(1)">›</button>
        </div>
        <div class="todo-week-row">
          <span v-for="name in weekDays" :key="name">{{ name }}</span>
        </div>
        <div class="todo-calendar-grid">
          <button
            v-for="day in calendarDays"
            :key="day.key"
            class="todo-calendar-day"
            :class="{
              outside: day.outside,
              today: day.key === today,
              selected: day.key === selectedDate,
              complete: dayState(day.key).completion === 'complete',
              incomplete: dayState(day.key).completion === 'incomplete'
            }"
            @click="selectDay(day)"
          >
            <span>{{ day.day }}</span>
            <small v-if="dayState(day.key).count">{{ dayState(day.key).count }} 项</small>
          </button>
        </div>
        <div class="todo-calendar-legend">
          <span><i class="complete"></i>全部完成</span>
          <span><i class="incomplete"></i>有未完成/延期</span>
        </div>
      </section>

      <section class="todo-day-pane">
        <div class="todo-day-heading">
          <div><h3>{{ selectedDateLabel }}</h3><p>{{ selectedDoneCount }}/{{ selectedItems.length }} 已完成</p></div>
        </div>
        <p v-if="error" class="todo-error">{{ error }}</p>
        <div v-if="loading" class="todo-empty">加载中…</div>
        <div v-else-if="!selectedItems.length" class="todo-empty">这天还没有待办。</div>
        <ul v-else class="todo-list">
          <li v-for="item in selectedItems" :key="item.id" class="todo-item" :class="{ done: item.status === 'DONE' }">
            <button class="todo-check" :title="item.status === 'DONE' ? '已完成' : '标记完成'" @click="toggle(item)">
              <svg v-if="item.status === 'DONE'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6"><path d="M20 6 9 17l-5-5" /></svg>
            </button>
            <div class="todo-main">
              <div class="todo-title">{{ item.title }}</div>
              <div v-if="item.note" class="todo-note">{{ item.note }}</div>
              <div class="todo-meta">
                <span v-if="item.dueTime" class="todo-time">{{ item.dueTime.slice(0, 5) }}</span>
                <span class="todo-src">{{ item.source === 'MANUAL' ? '手动' : '聊天' }}</span>
              </div>
            </div>
            <div class="todo-ops">
              <button class="todo-op" title="修改待办" @click="openEdit(item)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" /></svg>
              </button>
              <button v-if="item.status !== 'DONE'" class="todo-op" title="选择延期日期" @click="openDefer(item)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
              </button>
              <button class="todo-op danger" title="删除" @click="remove(item)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
              </button>
            </div>
          </li>
        </ul>

        <form class="todo-add todo-calendar-add" @submit.prevent="add">
          <strong>新增待办</strong>
          <input v-model="newTitle" class="todo-input" placeholder="要做什么" />
          <input v-model="newNote" class="todo-input note" placeholder="备注（可选）" />
          <div class="todo-date-time-row">
            <label><span>日期</span><input v-model="newDueDate" class="todo-input" type="date" required /></label>
            <label><span>时间</span><input v-model="newDueTime" class="todo-input" type="time" /></label>
          </div>
          <button class="auth-submit" :disabled="adding || !newTitle.trim() || !newDueDate">
            {{ adding ? '添加中…' : '添加到该日期' }}
          </button>
        </form>
      </section>
    </div>

    <div v-if="dialog" class="todo-dialog-backdrop" @click.self="dialog = null">
      <form v-if="dialog === 'edit'" class="todo-dialog" @submit.prevent="saveEdit">
        <div class="todo-dialog-head"><h3>修改待办</h3><button type="button" class="todo-dialog-close" @click="dialog = null">×</button></div>
        <label>标题<input v-model="editForm.title" class="todo-input" required /></label>
        <label>备注<input v-model="editForm.note" class="todo-input" /></label>
        <div class="todo-date-time-row">
          <label>日期<input v-model="editForm.dueDate" class="todo-input" type="date" required /></label>
          <label>时间<input v-model="editForm.dueTime" class="todo-input" type="time" /></label>
        </div>
        <button class="auth-submit" :disabled="saving || !editForm.title?.trim() || !editForm.dueDate">{{ saving ? '保存中…' : '保存修改' }}</button>
      </form>
      <form v-else class="todo-dialog" @submit.prevent="saveDefer">
        <div class="todo-dialog-head"><h3>选择延期日期</h3><button type="button" class="todo-dialog-close" @click="dialog = null">×</button></div>
        <p class="todo-dialog-copy">{{ editForm.title }}</p>
        <label>延期到<input v-model="editForm.dueDate" class="todo-input" type="date" :min="plusDays(editForm.currentDate, 1)" required /></label>
        <button class="auth-submit" :disabled="saving || !editForm.dueDate">{{ saving ? '延期中…' : '确认延期' }}</button>
      </form>
    </div>
  </aside>
</template>
