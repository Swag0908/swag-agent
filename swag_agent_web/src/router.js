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
