<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getUser } from '../auth'
import {
  installSkill,
  listSkills,
  refreshSkills,
  removeSkill,
  setSkillEnabled
} from '../api/skills'

const router = useRouter()
const user = getUser()
const isAdmin = computed(() => user?.role === 'ADMIN')

const skills = ref([])
const loading = ref(false)
const busy = ref('') // 正在操作的技能名，或 'refresh'
const error = ref('')
const ok = ref('')

const installRepo = ref('')
const installPath = ref('')
const installing = ref(false)

const enabledCount = computed(() => skills.value.filter((s) => s.enabled).length)
const builtinCount = computed(() => skills.value.filter((s) => s.source === 'builtin').length)
const externalCount = computed(() => skills.value.filter((s) => s.source === 'external').length)

async function load() {
  if (!isAdmin.value) return
  loading.value = true
  error.value = ''
  try {
    skills.value = (await listSkills()) || []
  } catch (e) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function note(message) {
  ok.value = message
  error.value = ''
}

function applyUpdated(updated) {
  const index = skills.value.findIndex((s) => s.name === updated.name)
  if (index >= 0) skills.value[index] = updated
}

async function toggle(skill) {
  if (busy.value) return
  busy.value = skill.name
  error.value = ''
  try {
    const updated = await setSkillEnabled(skill.name, !skill.enabled)
    applyUpdated(updated)
    note(`${updated.name} 已${updated.enabled ? '启用' : '停用'}，下一条消息即生效`)
  } catch (e) {
    error.value = e?.message || '操作失败'
  } finally {
    busy.value = ''
  }
}

async function rescan() {
  if (busy.value) return
  busy.value = 'refresh'
  error.value = ''
  try {
    skills.value = (await refreshSkills()) || []
    note('已重新扫描技能目录')
  } catch (e) {
    error.value = e?.message || '操作失败'
  } finally {
    busy.value = ''
  }
}

async function install() {
  const repo = installRepo.value.trim()
  if (!repo) {
    error.value = '请填写 Git 仓库地址，例如 anthropics/skills 或 https://github.com/anthropics/skills'
    return
  }
  if (installing.value) return
  installing.value = true
  error.value = ''
  try {
    const res = await installSkill(repo, installPath.value.trim())
    skills.value = res?.skills || []
    installRepo.value = ''
    installPath.value = ''
    note(`安装完成：${(res?.installed || []).join('、')}`)
  } catch (e) {
    console.error('技能安装失败', { repo, skillPath: installPath.value.trim(), error: e })
    error.value = e?.message || '安装失败'
  } finally {
    installing.value = false
  }
}

async function remove(skill) {
  if (!window.confirm(`删除外部技能「${skill.name}」？删除的是技能目录本身，内置技能不可删。`)) return
  if (busy.value) return
  busy.value = skill.name
  error.value = ''
  try {
    await removeSkill(skill.name)
    skills.value = skills.value.filter((s) => s.name !== skill.name)
    note(`已删除 ${skill.name}`)
  } catch (e) {
    error.value = e?.message || '删除失败'
  } finally {
    busy.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <div class="brand-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H9l1.5 2h8A1.5 1.5 0 0 1 20 7.5V18a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18V5.5Z" />
            <path d="M8 12h8M8 15.5h5" />
          </svg>
        </div>
        <div class="brand-text">
          <span class="brand-name">技能管理</span>
          <span class="brand-tag">{{ user?.displayName || user?.username }}</span>
        </div>
      </div>

      <div class="topbar-actions">
        <button class="nav-btn" @click="router.push({ name: 'notes' })">Markdown 笔记</button>
        <button class="nav-btn" @click="router.push({ name: 'sites' })">常用网站</button>
        <button class="nav-btn" @click="router.push({ name: 'stats' })">效率统计</button>
        <button class="nav-btn" @click="router.push({ name: 'traces' })">调用链</button>
        <button class="nav-btn" @click="router.push({ name: 'chat' })">返回聊天</button>
      </div>
    </header>

    <main class="stats-page">
      <div class="stats-wrap">
        <p v-if="!isAdmin" class="stats-empty">技能管理仅管理员可用，请用管理员账号登录。</p>

        <template v-else>
          <div class="stats-summary">
            <div class="stat-box">
              <span class="stat-num">{{ skills.length }}</span>
              <span class="stat-label">全部技能</span>
            </div>
            <div class="stat-box">
              <span class="stat-num">{{ enabledCount }}</span>
              <span class="stat-label">启用中</span>
            </div>
            <div class="stat-box">
              <span class="stat-num">{{ builtinCount }}</span>
              <span class="stat-label">内置</span>
            </div>
            <div class="stat-box">
              <span class="stat-num">{{ externalCount }}</span>
              <span class="stat-label">外部</span>
            </div>
          </div>

          <p v-if="error" class="todo-error">{{ error }}</p>
          <p v-if="ok" class="reg-ok">{{ ok }}</p>

          <section class="skill-section">
            <h3>从 Git 仓库安装 <span class="reg-hint">网上的 agent skill 目录可直接装，无需写代码</span></h3>
            <div class="skill-install">
              <input
                v-model="installRepo"
                type="text"
                placeholder="anthropics/skills 或 https://github.com/anthropics/skills"
                @keyup.enter="install"
              />
              <input
                v-model="installPath"
                type="text"
                placeholder="技能路径（可选，如 skills/webapp-testing）"
                @keyup.enter="install"
              />
              <button type="button" class="reg-btn primary" :disabled="installing" @click="install">
                {{ installing ? '安装中…' : '安装' }}
              </button>
              <button type="button" class="reg-btn" :disabled="!!busy" @click="rescan">
                {{ busy === 'refresh' ? '扫描中…' : '重新扫描' }}
              </button>
            </div>
            <p class="skill-hint">
              留空技能路径时：仓库根有 SKILL.md 就整仓装为一个技能，否则从一级子目录里找；形如
              <code>skills/&lt;name&gt;/SKILL.md</code> 的仓库请填写完整路径。手工把技能目录丢进
              后端 <code>skills-data/</code> 目录同样生效，随后点「重新扫描」即可。
            </p>
          </section>

          <section class="skill-section">
            <h3>技能列表 <span class="reg-hint">停用的技能不再注入提示词，状态存在数据库里、重启后保持</span></h3>

            <div v-if="loading" class="todo-empty">加载中…</div>
            <div v-else-if="!skills.length" class="todo-empty">
              还没有任何技能。可以在上面填一个仓库地址安装，或把含 SKILL.md 的目录放进后端 skills-data/ 后重新扫描。
            </div>

            <ul v-else class="skill-list">
              <li v-for="s in skills" :key="s.name" class="skill-card" :class="{ off: !s.enabled }">
                <div class="skill-main">
                  <div class="skill-title">
                    <strong>{{ s.name }}</strong>
                    <span class="skill-badge" :class="s.source">{{ s.source === 'builtin' ? '内置' : '外部' }}</span>
                    <span class="skill-badge" :class="{ on: s.enabled }">{{ s.enabled ? '启用中' : '已停用' }}</span>
                  </div>
                  <p class="skill-desc">{{ s.description }}</p>
                  <p class="skill-path" :title="s.filePath">{{ s.bodyChars }} 字符 · {{ s.filePath }}</p>
                </div>
                <div class="skill-actions">
                  <button
                    type="button"
                    class="mem-switch"
                    :class="{ on: s.enabled }"
                    role="switch"
                    :aria-checked="s.enabled"
                    :disabled="busy === s.name"
                    :title="s.enabled ? '停用' : '启用'"
                    @click="toggle(s)"
                  >
                    <span></span>
                  </button>
                  <button
                    v-if="s.source === 'external'"
                    type="button"
                    class="reg-btn ghost"
                    :disabled="busy === s.name"
                    @click="remove(s)"
                  >
                    删除
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
