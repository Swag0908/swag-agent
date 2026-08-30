<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getStats } from '../api/todo'
import { getUser } from '../auth'

const router = useRouter()
const user = getUser()

const stats = ref([])
const loading = ref(false)
const error = ref('')
const range = ref(7) // 默认最近 7 天

async function load() {
  loading.value = true
  error.value = ''
  try {
    stats.value = await getStats(null, null)
  } catch (e) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function fmtDate(date) {
  if (!date) return ''
  const d = new Date(date + 'T00:00:00')
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${m}-${day}`
}

const total = computed(() =>
  stats.value.reduce(
    (acc, s) => ({
      created: acc.created + s.createdCount,
      completed: acc.completed + s.completedCount,
      pending: acc.pending + s.pendingCount,
      deferred: acc.deferred + s.deferredCount
    }),
    { created: 0, completed: 0, pending: 0, deferred: 0 }
  )
)

function maxCount() {
  return Math.max(1, ...stats.value.map((s) => s.createdCount + s.pendingCount + s.deferredCount))
}

onMounted(load)
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
          <span class="brand-name">待办统计</span>
          <span class="brand-tag">{{ user?.displayName || user?.username }}</span>
        </div>
      </div>

      <div class="topbar-actions">
        <button class="nav-btn" @click="router.push({ name: 'chat' })">返回聊天</button>
      </div>
    </header>

    <main class="stats-page">
      <div class="stats-wrap">
        <div class="stats-summary">
          <div class="stat-box">
            <span class="stat-num">{{ total.completed }}</span>
            <span class="stat-label">已完成</span>
          </div>
          <div class="stat-box">
            <span class="stat-num">{{ total.pending }}</span>
            <span class="stat-label">未完成</span>
          </div>
          <div class="stat-box">
            <span class="stat-num">{{ total.deferred }}</span>
            <span class="stat-label">延期</span>
          </div>
          <div class="stat-box">
            <span class="stat-num">{{ total.created }}</span>
            <span class="stat-label">新增</span>
          </div>
        </div>

        <p v-if="error" class="todo-error">{{ error }}</p>
        <div v-if="loading" class="stats-empty">加载中…</div>
        <div v-else-if="!stats.length" class="stats-empty">暂无统计数据，先去安排今天的待办吧。</div>

        <div v-else class="stats-list">
          <div v-for="s in stats" :key="s.statDate" class="stats-day">
            <div class="stats-day-head">
              <span class="stats-date">{{ fmtDate(s.statDate) }}</span>
              <span class="stats-rate">{{ s.completionRate == null ? '—' : s.completionRate + '%' }}</span>
            </div>
            <div class="stats-bar">
              <span
                class="bar-seg done"
                :style="{ width: (s.completedCount / maxCount()) * 100 + '%' }"
                :title="'完成 ' + s.completedCount"
              ></span>
              <span
                class="bar-seg defer"
                :style="{ width: (s.deferredCount / maxCount()) * 100 + '%' }"
                :title="'延期 ' + s.deferredCount"
              ></span>
              <span
                class="bar-seg pend"
                :style="{ width: (s.pendingCount / maxCount()) * 100 + '%' }"
                :title="'未完成 ' + s.pendingCount"
              ></span>
            </div>
            <div class="stats-legend">
              完成 {{ s.completedCount }} · 延期 {{ s.deferredCount }} · 未完成 {{ s.pendingCount }} · 新增 {{ s.createdCount }}
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
