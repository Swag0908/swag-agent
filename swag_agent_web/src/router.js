import { createRouter, createWebHistory } from 'vue-router'
import { isAuthed } from './auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('./views/LoginView.vue')
  },
  {
    path: '/',
    name: 'chat',
    component: () => import('./views/ChatView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/stats',
    name: 'stats',
    component: () => import('./views/StatsView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/sites',
    name: 'sites',
    component: () => import('./views/SitesView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/notes',
    name: 'notes',
    component: () => import('./views/NotesView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/skills',
    name: 'skills',
    component: () => import('./views/SkillsView.vue'),
    meta: { requiresAuth: true }
  },
  {
    // 调用链：仅 ADMIN 可见/可用（后端 /audit/chains 同样只放行 ADMIN）
    path: '/traces',
    name: 'traces',
    component: () => import('./views/TracesView.vue'),
    meta: { requiresAuth: true }
  }
]

export const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  if (to.meta.requiresAuth && !isAuthed()) {
    return { name: 'login' }
  }
  if (to.name === 'login' && isAuthed()) {
    return { name: 'chat' }
  }
})
