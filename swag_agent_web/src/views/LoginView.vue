<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login, register } from '../api/auth'
import { setAuth } from '../auth'

const router = useRouter()
const mode = ref('login') // 'login' | 'register'
const username = ref('')
const password = ref('')
const displayName = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请填写用户名和密码'
    return
  }
  loading.value = true
  try {
    const res =
      mode.value === 'login'
        ? await login({ username: username.value.trim(), password: password.value })
        : await register({
            username: username.value.trim(),
            password: password.value,
            displayName: displayName.value.trim()
          })
    setAuth(res)
    router.push({ name: 'chat' })
  } catch (e) {
    error.value = e?.message || '操作失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-brand">
        <div class="auth-logo">
          <img src="/brand/cowhorse-glyph-256.png" alt="" />
        </div>
        <div>
          <h1 class="auth-title">Cowhourse Legend</h1>
          <p class="auth-sub">成为牛马传奇</p>
        </div>
      </div>

      <div class="auth-tabs">
        <button
          type="button"
          :class="{ active: mode === 'login' }"
          @click="mode = 'login'"
        >
          登录
        </button>
        <button
          type="button"
          :class="{ active: mode === 'register' }"
          @click="mode = 'register'"
        >
          注册
        </button>
      </div>

      <form class="auth-form" @submit.prevent="submit">
        <label class="field">
          <span>用户名</span>
          <input v-model="username" type="text" autocomplete="username" placeholder="请输入用户名" />
        </label>

        <label v-if="mode === 'register'" class="field">
          <span>昵称（可选）</span>
          <input v-model="displayName" type="text" placeholder="显示名称" />
        </label>

        <label class="field">
          <span>密码</span>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="至少 6 位"
          />
        </label>

        <p v-if="error" class="auth-error">{{ error }}</p>

        <button type="submit" class="auth-submit" :disabled="loading">
          {{ loading ? '请稍候…' : mode === 'login' ? '登 录' : '注册并登录' }}
        </button>
      </form>

    </div>
  </div>
</template>
