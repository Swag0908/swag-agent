// 审计/调用链接口（后端仅 ADMIN 放行，前端只负责隐藏入口，权限以后端为准）。
import { api } from './http'

export const listChains = (limit = 30) => api(`/audit/chains?limit=${limit}`)
