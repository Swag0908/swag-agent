<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getUser } from '../auth'
import { listChains } from '../api/audit'

const router = useRouter()
const user = getUser()
const isAdmin = computed(() => user?.role === 'ADMIN')

const chains = ref([])
const loading = ref(false)
const error = ref('')
const ok = ref('')
const onlyProblems = ref(false)
const traceInput = ref('')

const LIMIT = 50

// 状态 -> 展示文案与配色。后端只会给这几种值。
const STATUS_TEXT = {
  SUCCEEDED: { text: '成功', tone: 'ok' },
  REJECTED: { text: '被拒绝', tone: 'warn' },
  WAITING_CONFIRMATION: { text: '待确认', tone: 'warn' },
  FAILED: { text: '失败', tone: 'bad' },
  IN_PROGRESS: { text: '进行中', tone: 'run' },
  UNKNOWN: { text: '未知', tone: 'muted' }
}

function statusOf(chain) {
  return STATUS_TEXT[chain?.status] || { text: chain?.status || '未知', tone: 'muted' }
}

const problemCount = computed(
  () => chains.value.filter((c) => c.status === 'FAILED' || c.status === 'REJECTED').length
)
const runningCount = computed(() => chains.value.filter((c) => c.status === 'IN_PROGRESS').length)
const succeededCount = computed(() => chains.value.filter((c) => c.status === 'SUCCEEDED').length)
const tracesCount = computed(() => chains.value.filter((c) => c.traceId).length)

const visibleChains = computed(() =>
  onlyProblems.value
    ? chains.value.filter((c) => c.status !== 'SUCCEEDED' && c.status !== 'IN_PROGRESS')
    : chains.value
)

async function load() {
  if (!isAdmin.value) return
  loading.value = true
  error.value = ''
  try {
    chains.value = (await listChains(LIMIT)) || []
    ok.value = `已刷新，共 ${chains.value.length} 条调用链`
  } catch (e) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

/** 新标签页打开；同源相对地址，浏览器会自动带上 swag_zipkin_token 票据。 */
function openZipkin(url) {
  if (!url) return
  window.open(url, '_blank', 'noopener')
}

/** 允许直接粘完整链接，或只粘 traceId。 */
function openPastedTrace() {
  const raw = traceInput.value.trim()
  if (!raw) {
    error.value = '先粘贴 traceId 或 /zipkin/traces/... 链接'
    return
  }
  const traceId = raw.includes('/') ? raw.split('/').filter(Boolean).pop() : raw
  openZipkin(`/zipkin/traces/${encodeURIComponent(traceId)}`)
}

async function copyText(value) {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    ok.value = `已复制 ${value}`
  } catch {
    error.value = '浏览器不允许写剪贴板，请手动选中复制'
  }
}

function timeText(iso) {
  if (!iso) return '-'
  const date = new Date(iso)
  return date.toLocaleString('zh-CN', { hour12: false })
}

function durationText(chain) {
  if (!chain?.startedAt || !chain?.endedAt) return ''
  const ms = new Date(chain.endedAt) - new Date(chain.startedAt)
  if (!Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

onMounted(load)
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <div class="brand-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M3 12h4l2.5-6 3 12 2.5-6h6" />
          </svg>
        </div>
        <div class="brand-text">
          <span class="brand-name">调用链</span>
          <span class="brand-tag">{{ user?.displayName || user?.username }}</span>
        </div>
      </div>

      <div class="topbar-actions">
        <button class="nav-btn" @click="router.push({ name: 'notes' })">Markdown 笔记</button>
        <button class="nav-btn" @click="router.push({ name: 'sites' })">常用网站</button>
        <button class="nav-btn" @click="router.push({ name: 'stats' })">效率统计</button>
        <button v-if="isAdmin" class="nav-btn" @click="router.push({ name: 'skills' })">技能管理</button>
        <button class="nav-btn" @click="router.push({ name: 'chat' })">返回聊天</button>
      </div>
    </header>

    <main class="stats-page">
      <div class="stats-wrap">
        <p v-if="!isAdmin" class="stats-empty">
          调用链仅管理员可用，请用管理员账号登录。普通账号打开 Zipkin 也会被后端拒绝。
        </p>

        <template v-else>
          <div class="stats-summary">
            <div class="stat-box">
              <span class="stat-num">{{ chains.length }}</span>
              <span class="stat-label">调用链</span>
            </div>
            <div class="stat-box">
              <span class="stat-num">{{ succeededCount }}</span>
              <span class="stat-label">成功</span>
            </div>
            <div class="stat-box">
              <span class="stat-num">{{ problemCount }}</span>
              <span class="stat-label">失败/拒绝</span>
            </div>
            <div class="stat-box">
              <span class="stat-num">{{ runningCount }}</span>
              <span class="stat-label">进行中</span>
            </div>
          </div>

          <p v-if="error" class="todo-error">{{ error }}</p>
          <p v-if="ok" class="reg-ok">{{ ok }}</p>

          <section class="skill-section">
            <h3>
              打开 Zipkin
              <span class="reg-hint">
                新标签页打开；只有管理员登录态能过 nginx 的门禁，链接过期就回登录页
              </span>
            </h3>
            <div class="skill-install">
              <input
                v-model="traceInput"
                type="text"
                placeholder="粘贴 traceId 或 /zipkin/traces/... 链接直达某条调用链"
                @keyup.enter="openPastedTrace"
              />
              <button type="button" class="reg-btn primary" @click="openPastedTrace">直达</button>
              <button type="button" class="reg-btn" @click="openZipkin('/zipkin/')">
                打开 Zipkin 搜索台
              </button>
              <button type="button" class="reg-btn ghost" :disabled="loading" @click="load">
                {{ loading ? '刷新中…' : '刷新列表' }}
              </button>
            </div>
            <p class="skill-hint">
              带 traceId 的链共 {{ tracesCount }} 条。列表来自审计表 <code>audit_event</code>，
              按 <code>audit_id</code> 聚合：一次请求 = 一条链 = 一个 trace。
            </p>
          </section>

          <section class="skill-section">
            <h3>
              最近调用
              <span class="reg-hint">
                数据是你每次操作真实产生的；先去系统里发一条消息或做一次操作，再回来点刷新
              </span>
            </h3>

            <label class="trace-filter">
              <input v-model="onlyProblems" type="checkbox" />
              <span>只看失败/被拒绝</span>
            </label>

            <div v-if="loading && !chains.length" class="todo-empty">加载中…</div>
            <div v-else-if="!chains.length" class="todo-empty">
              还没有审计数据。到聊天页发一条消息或做任意操作，然后点上面的「刷新列表」。
            </div>
            <div v-else-if="!visibleChains.length" class="todo-empty">没有符合筛选条件的调用链。</div>

            <ul v-else class="skill-list">
              <li v-for="c in visibleChains" :key="c.auditId" class="skill-card">
                <div class="skill-main">
                  <div class="skill-title">
                    <strong>{{ c.method || 'REQ' }} {{ c.path || '(未知路径)' }}</strong>
                    <span class="skill-badge" :class="statusOf(c).tone">{{ statusOf(c).text }}</span>
                    <span v-if="c.httpStatus" class="skill-badge">HTTP {{ c.httpStatus }}</span>
                    <span v-if="!c.traceId" class="skill-badge">无 trace</span>
                  </div>
                  <p class="skill-desc">
                    {{ timeText(c.startedAt) }}
                    <template v-if="durationText(c)"> · 耗时 {{ durationText(c) }}</template>
                    · {{ c.actorName || c.actorId || '未知用户' }}
                    · {{ c.eventCount }} 条事件
                  </p>
                  <p class="skill-path" :title="c.auditId">audit_id: {{ c.auditId }}</p>
                  <p v-if="c.traceId" class="skill-path" :title="c.traceId">trace_id: {{ c.traceId }}</p>
                </div>
                <div class="skill-actions">
                  <button
                    type="button"
                    class="reg-btn primary"
                    :disabled="!c.traceId"
                    :title="c.traceId ? '新标签页打开 Zipkin 瀑布图' : '这条链没有 trace（未采样或未启用导出）'"
                    @click="openZipkin(c.zipkinTraceUrl)"
                  >
                    查看调用链
                  </button>
                  <button
                    v-if="c.traceId"
                    type="button"
                    class="reg-btn ghost"
                    @click="copyText(c.traceId)"
                  >
                    复制 traceId
                  </button>
                </div>
              </li>
            </ul>
          </section>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.trace-filter {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 12px;
  font-size: 13px;
  opacity: 0.85;
  cursor: pointer;
}

.trace-filter input {
  width: auto;
  margin: 0;
}

.skill-badge.ok {
  color: #0f9d58;
  border-color: rgba(15, 157, 88, 0.45);
}

.skill-badge.warn {
  color: #d98324;
  border-color: rgba(217, 131, 36, 0.45);
}

.skill-badge.bad {
  color: #e05353;
  border-color: rgba(224, 83, 83, 0.45);
}

.skill-badge.run {
  color: #4a8fe7;
  border-color: rgba(74, 143, 231, 0.45);
}

.skill-badge.muted {
  opacity: 0.6;
}
</style>
