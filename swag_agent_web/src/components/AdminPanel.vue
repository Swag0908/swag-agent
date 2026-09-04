<script setup>
import { ref, watch } from 'vue'
import { getUser } from '../auth'
import {
  getRegisterSettings,
  updateRegisterSettings,
  regenerateRegisterCode,
  listUsers,
  setUserRole
} from '../api/admin'

const props = defineProps({
  open: { type: Boolean, default: false }
})
const emit = defineEmits(['close'])

const selfId = getUser()?.userId ?? null

const loaded = ref(false)
const busy = ref(false)
const error = ref('')
const ok = ref('')

const enabled = ref(true)
const code = ref('')
const users = ref([])
const custom = ref('')

async function refresh() {
  busy.value = true
  error.value = ''
  try {
    const [settings, userList] = await Promise.all([getRegisterSettings(), listUsers()])
    enabled.value = !!settings.registrationEnabled
    code.value = settings.registerCode || ''
    users.value = Array.isArray(userList) ? userList : []
    loaded.value = true
  } catch (e) {
    error.value = e?.message || '加载失败'
  } finally {
    busy.value = false
  }
}

watch(
  () => props.open,
  (v) => {
    if (v) {
      ok.value = ''
      custom.value = ''
      refresh()
    }
  }
)

function note(message) {
  ok.value = message
  error.value = ''
}

async function toggleEnabled() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const settings = await updateRegisterSettings({ registrationEnabled: !enabled.value })
    enabled.value = !!settings.registrationEnabled
    note(enabled.value ? '已开放注册' : '已关闭注册，新用户暂时无法注册')
  } catch (e) {
    error.value = e?.message || '操作失败'
  } finally {
    busy.value = false
  }
}

async function rotate() {
  if (busy.value) return
  if (!window.confirm('将生成一条全新的注册码，旧注册码立即失效。确定换新？')) return
  busy.value = true
  error.value = ''
  try {
    const settings = await regenerateRegisterCode()
    code.value = settings.registerCode || ''
    custom.value = ''
    note('已换新，旧注册码立即失效，请把新码发给需要注册的人')
  } catch (e) {
    error.value = e?.message || '操作失败'
  } finally {
    busy.value = false
  }
}

async function applyCustom() {
  const value = custom.value.trim()
  if (!value) {
    error.value = '请先输入要设置的注册码（6-40 位）'
    return
  }
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const settings = await updateRegisterSettings({ registerCode: value })
    code.value = settings.registerCode || ''
    custom.value = ''
    note('注册码已更新')
  } catch (e) {
    error.value = e?.message || '操作失败'
  } finally {
    busy.value = false
  }
}

async function copyCode() {
  if (!code.value) return
  try {
    await navigator.clipboard.writeText(code.value)
    note('注册码已复制，可直接发给对方')
  } catch {
    error.value = '复制失败，请手动选中复制'
  }
}

async function toggleUserRole(userItem) {
  const promote = userItem.role !== 'ADMIN'
  const label = `${userItem.displayName || userItem.username}`
  if (!window.confirm(`${promote ? `将 ${label} 设为管理员` : `取消 ${label} 的管理员`}，确定？`)) return
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await setUserRole(userItem.id, promote ? 'ADMIN' : 'USER')
    note(promote ? `已将 ${label} 设为管理员` : `已取消 ${label} 的管理员`)
    const userList = await listUsers()
    users.value = Array.isArray(userList) ? userList : []
  } catch (e) {
    error.value = e?.message || '操作失败'
  } finally {
    busy.value = false
  }
}

function fmtTime(ms) {
  if (!ms) return ''
  const d = new Date(ms)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
</script>

<template>
  <transition name="fade">
    <div v-if="open" class="todo-mask" @click="emit('close')"></div>
  </transition>

  <aside class="todo-drawer memory-drawer" :class="{ open }">
    <header class="todo-head">
      <div>
        <h2>注册管理</h2>
        <p class="todo-sub">注册码、新用户注册开关与管理员设置（仅管理员可见）</p>
      </div>
      <button class="icon-btn" title="关闭" @click="emit('close')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </header>

    <div class="todo-body admin-body">
      <p v-if="error" class="todo-error">{{ error }}</p>
      <p v-if="ok" class="reg-ok">{{ ok }}</p>

      <div v-if="!loaded" class="todo-empty">加载中…</div>
      <template v-else>
        <section class="reg-section">
          <h3>新用户注册</h3>
          <div class="memory-toggle">
            <div>
              <strong>{{ enabled ? '允许注册' : '已关闭注册' }}</strong>
              <span>关闭后，即使注册码正确也无法注册新账号，防止恶意消耗</span>
            </div>
            <button
              type="button"
              class="mem-switch"
              :class="{ on: enabled }"
              :disabled="busy"
              role="switch"
              :aria-checked="enabled"
              @click="toggleEnabled"
            >
              <span></span>
            </button>
          </div>
        </section>

        <section class="reg-section">
          <h3>注册码 <span class="reg-hint">请私下分享给信任的人</span></h3>
          <div class="reg-code-box">
            <code>{{ code }}</code>
            <button type="button" class="reg-copy" :disabled="busy" @click="copyCode">复制</button>
          </div>
          <div class="reg-actions">
            <button type="button" class="reg-btn" :disabled="busy" @click="rotate">换新注册码</button>
            <span class="reg-actions-hint">换新后旧码立即失效</span>
          </div>
          <div class="reg-custom">
            <input v-model="custom" type="text" placeholder="自定义注册码（可选，6-40 位）" @keyup.enter="applyCustom" />
            <button type="button" class="reg-btn primary" :disabled="busy" @click="applyCustom">设为注册码</button>
          </div>
        </section>

        <section class="reg-section">
          <h3>用户与管理员</h3>
          <ul class="reg-users">
            <li v-for="u in users" :key="u.id" class="reg-user">
              <div class="reg-user-avatar">{{ (u.displayName || u.username || '?').slice(0, 1).toUpperCase() }}</div>
              <div class="reg-user-main">
                <strong>
                  {{ u.displayName || u.username }}
                  <span v-if="u.id === selfId" class="reg-me">我</span>
                </strong>
                <span>@{{ u.username }} · {{ fmtTime(u.createdAtMs) }}</span>
              </div>
              <span class="reg-role" :class="{ admin: u.role === 'ADMIN' }">
                {{ u.role === 'ADMIN' ? '管理员' : '成员' }}
              </span>
              <button
                v-if="u.id !== selfId"
                type="button"
                class="reg-btn ghost"
                :disabled="busy"
                @click="toggleUserRole(u)"
              >
                {{ u.role === 'ADMIN' ? '取消管理员' : '设为管理员' }}
              </button>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </aside>
</template>
