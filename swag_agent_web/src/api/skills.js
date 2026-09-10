// 技能包管理接口（后端仅 ADMIN 角色放行，前端只负责隐藏入口，权限以后端为准）。
import { api } from './http'

export const listSkills = () => api('/auth/admin/skills')

export const setSkillEnabled = (name, enabled) =>
  api(`/auth/admin/skills/${encodeURIComponent(name)}`, { method: 'PUT', body: { enabled } })

export const refreshSkills = () => api('/auth/admin/skills/refresh', { method: 'POST' })

export const installSkill = (repoUrl, skillPath) =>
  api('/auth/admin/skills/install', {
    method: 'POST',
    body: { repoUrl, skillPath: skillPath || null },
    // 后端 git clone 最多等待 60 秒；额外留出网络传输与错误响应时间。
    timeoutMs: 70_000
  })

export const removeSkill = (name) =>
  api(`/auth/admin/skills/${encodeURIComponent(name)}`, { method: 'DELETE' })
