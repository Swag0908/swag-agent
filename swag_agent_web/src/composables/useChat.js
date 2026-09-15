import { reactive, ref, watch, computed } from 'vue'
import { streamChat } from '../api/chat'
import {
  listConversations,
  createConversation,
  getConversationMessages,
  deleteConversation as deleteConversationApi,
  clearConversations as clearConversationsApi,
  setConversationFavorite as setConversationFavoriteApi,
  reorderFavoriteConversations as reorderFavoriteConversationsApi,
  deleteConversationMessage as deleteConversationMessageApi
} from '../api/conversations'

let idSeq = 0
const nextId = () => ++idSeq

const MODEL_STORAGE_KEY = 'swagAgent.model'
export const ACTIVE_CONVERSATION_KEY = 'swagAgent.activeConversation'

// 后端 SelectModelTool 支持 id 1（V4 Flash）与 2（V4 Pro），默认 1
function storedModelId() {
  const v = Number(localStorage.getItem(MODEL_STORAGE_KEY))
  return v === 1 || v === 2 ? v : 1
}

function titleOf(text) {
  const flat = String(text || '').replace(/\s+/g, ' ').trim()
  return flat.length > 24 ? flat.slice(0, 24) + '…' : flat
}

/** 会话在列表里显示的名字：收藏备注优先，其次会话原标题。 */
export function conversationLabel(conv) {
  if (!conv) return '新对话'
  const note = (conv.favoriteNote || '').trim()
  if (conv.favorite && note) return note
  return conv.title || '新对话'
}

export function useChat() {
  const messages = reactive([])
  const sending = ref(false)
  const modelId = ref(storedModelId())

  // ---- DeepSeek 式工作区：多会话 ----
  const conversations = ref([]) // 服务端返回的历史会话列表（收藏置顶）
  const conversationId = ref(null) // 当前激活会话（null = 新建会话草稿）
  const conversationTitle = ref('') // 当前会话标题（用于顶栏展示）
  const loadingHistory = ref(false)

  // 记住用户选择的模型，下次打开仍是上次选的模型
  watch(modelId, (v) => localStorage.setItem(MODEL_STORAGE_KEY, String(v)))

  let controller = null

  const hasConversation = computed(() => conversationId.value != null)
  const favoriteConversations = computed(() => conversations.value.filter((c) => c.favorite))

  /** 拉取历史会话列表（顺序由后端决定：收藏置顶 + 最近活跃倒序）。 */
  async function refreshConversations() {
    try {
      const list = await listConversations()
      conversations.value = Array.isArray(list) ? list : []
    } catch (e) {
      conversations.value = conversations.value || []
      // 列表加载失败不阻断聊天；保留本地已有数据
      console.error('加载会话列表失败', e)
    }
  }

  /**
   * 用服务端消息覆盖本地视图。
   * 只有服务端返回的消息才带 serverId，删除单条对话时就靠这个 id 定位。
   *
   * <p>尽量复用本地已有的 id：`:key` 变化会让 Vue 重建整个消息组件，
   * 表现就是每轮回复结束后整屏消息重放一次入场动画。
   * - 先按 serverId 匹配（重新打开会话、删除消息后的对齐）
   * - preserveLocalIds 时再按位置兜底匹配（刚发完一轮，本地那两条还没有 serverId）
   */
  function applyServerMessages(list, { preserveLocalIds = false } = {}) {
    const incoming = Array.isArray(list) ? list : []
    const previous = messages.slice()
    const reused = new Set()

    const next = incoming.map((m, index) => {
      const role = m.role === 'user' ? 'user' : 'assistant'
      let local = m.id == null
        ? null
        : previous.find((p) => p.serverId != null && String(p.serverId) === String(m.id))
      if (!local && preserveLocalIds) {
        const candidate = previous[index]
        if (candidate && !reused.has(candidate.id) && candidate.role === role) {
          local = candidate
        }
      }
      if (local) reused.add(local.id)
      return {
        id: local ? local.id : nextId(),
        serverId: m.id ?? null,
        role,
        content: m.content || '',
        streaming: false,
        error: local ? local.error : false
      }
    })

    messages.splice(0, messages.length, ...next)
  }

  /** 静默对齐当前会话的消息（不显示「正在载入历史对话」遮罩）。 */
  async function syncMessages(id, options) {
    if (id == null) return
    const list = await getConversationMessages(id)
    if (String(conversationId.value) !== String(id)) return // 期间又切走了会话，丢弃结果
    applyServerMessages(list, options)
  }

  /** 新建会话：仅清空当前视图，首个提问发出时才在后端真正建档。 */
  function newConversation() {
    stop()
    messages.splice(0, messages.length)
    conversationId.value = null
    conversationTitle.value = ''
    localStorage.removeItem(ACTIVE_CONVERSATION_KEY)
  }

  /** 打开一个历史会话：拉取历史消息后即可继续对话（记忆按该会话 id 隔离）。 */
  async function openConversation(conv) {
    if (!conv || conv.id == null) return
    stop()
    conversationId.value = conv.id
    conversationTitle.value = conv.title || ''
    messages.splice(0, messages.length)
    loadingHistory.value = true
    localStorage.setItem(ACTIVE_CONVERSATION_KEY, String(conv.id))
    try {
      applyServerMessages(await getConversationMessages(conv.id))
    } catch (e) {
      // 会话不存在/已失效：退出该会话状态，回到空白新会话
      conversationId.value = null
      conversationTitle.value = ''
      localStorage.removeItem(ACTIVE_CONVERSATION_KEY)
      messages.push({
        id: nextId(),
        serverId: null,
        role: 'assistant',
        content: '> ⚠️ 加载历史消息失败：' + (e?.message || '网络错误'),
        streaming: false,
        error: true
      })
    } finally {
      loadingHistory.value = false
    }
  }

  /** 删除会话并同步本地列表；删除当前会话后回到新会话草稿。 */
  async function deleteConversation(conv) {
    if (!conv || conv.id == null) return
    const deletingActive = String(conv.id) === String(conversationId.value)
    if (deletingActive && sending.value) {
      throw new Error('请先停止当前回复，再删除这个会话')
    }

    await deleteConversationApi(conv.id)
    conversations.value = conversations.value.filter(
      (item) => String(item.id) !== String(conv.id)
    )
    if (deletingActive) newConversation()
  }

  /** 清空全部历史会话（后端同时回收记忆与审计记录）。 */
  async function clearConversations() {
    stop()
    const result = await clearConversationsApi()
    conversations.value = []
    newConversation()
    return result?.deleted ?? 0
  }

  /** 收藏 / 取消收藏；favorite=true 时可选传入备注名。 */
  async function setFavorite(conv, favorite, note = null) {
    if (!conv || conv.id == null) return
    await setConversationFavoriteApi(conv.id, favorite, note)
    // 收藏会改变分组与排序，交给后端重算顺序最稳
    await refreshConversations()
  }

  /** 保存收藏备注名（不改会话原标题）。 */
  async function renameFavorite(conv, note) {
    if (!conv || conv.id == null) return
    const trimmed = String(note || '').trim()
    await setConversationFavoriteApi(conv.id, true, trimmed || null)
    await refreshConversations()
  }

  /** 收藏区拖拽排序：先本地重排让界面立即响应，再用服务端结果校准。 */
  async function reorderFavorites(orderedIds) {
    const ids = (orderedIds || []).map((id) => String(id))
    const byId = new Map(conversations.value.map((c) => [String(c.id), c]))
    const picked = ids.map((id) => byId.get(id)).filter(Boolean)
    const rest = conversations.value.filter((c) => !ids.includes(String(c.id)))
    conversations.value = [...picked, ...rest]

    const list = await reorderFavoriteConversationsApi(orderedIds)
    if (Array.isArray(list)) conversations.value = list
  }

  /**
   * 删除会话里的一条对话。后端会把与它配对的那条一起删除（提问 + 紧随的回答），
   * 并按剩余消息重建该会话的记忆，返回剩余消息用于对齐界面。
   */
  async function deleteMessage(message) {
    if (!message || conversationId.value == null) return
    if (sending.value) {
      throw new Error('请先停止当前回复，再删除这条对话')
    }

    const index = messages.findIndex((m) => m.id === message.id)
    if (index < 0) return

    let serverId = message.serverId
    if (serverId == null) {
      // 服务端 id 还没回填（例如上一轮同步失败），先对齐一次再删。
      // preserveLocalIds 保证同一位置还是同一条消息，下面按位置取回才不会错位。
      await syncMessages(conversationId.value, { preserveLocalIds: true })
      const target = messages[index]
      serverId = target && target.role === message.role ? target.serverId : null
    }
    if (serverId == null) {
      throw new Error('这条对话还没有保存到服务端，暂时无法删除')
    }

    applyServerMessages(await deleteConversationMessageApi(conversationId.value, serverId))
  }

  async function send(raw) {
    const text = String(raw ?? '').trim()
    if (!text || sending.value) return

    // 草稿会话首次提问：先在后端建会话，拿到 id 后再流式对话
    if (conversationId.value == null) {
      try {
        const created = await createConversation()
        conversationId.value = created.id
        conversationTitle.value = titleOf(text)
        localStorage.setItem(ACTIVE_CONVERSATION_KEY, String(created.id))
        // 立即插入列表顶部，避免刚发出时列表看不到
        conversations.value.unshift({
          id: created.id,
          title: titleOf(text),
          favorite: false,
          favoriteNote: null,
          createdAtMs: created.createdAtMs,
          updatedAtMs: created.updatedAtMs
        })
      } catch (e) {
        messages.push({
          id: nextId(),
          serverId: null,
          role: 'assistant',
          content: '> ⚠️ 创建会话失败：' + (e?.message || '网络错误'),
          streaming: false,
          error: true
        })
        return
      }
    }

    messages.push({ id: nextId(), serverId: null, role: 'user', content: text })

    const assistant = reactive({
      id: nextId(),
      serverId: null,
      role: 'assistant',
      content: '',
      streaming: true,
      error: false
    })
    messages.push(assistant)

    sending.value = true
    controller = new AbortController()

    try {
      await streamChat({
        model: modelId.value,
        message: text,
        conversationId: conversationId.value,
        signal: controller.signal,
        onDelta: (chunk) => {
          assistant.content += chunk
        }
      })
      assistant.streaming = false
    } catch (err) {
      assistant.streaming = false
      if (err && err.name === 'AbortError') {
        if (!assistant.content.trim()) {
          assistant.content = '（已停止）'
        }
      } else {
        assistant.error = true
        assistant.content +=
          (assistant.content ? '\n\n' : '') + '> ⚠️ ' + (err?.message || '网络错误')
      }
    } finally {
      sending.value = false
      controller = null
      // 会话标题/排序在服务端已更新，静默刷新列表保持与后端一致
      await refreshConversations()
      const cur = conversations.value.find((c) => String(c.id) === String(conversationId.value))
      if (cur) conversationTitle.value = cur.title || conversationTitle.value
      // 回填服务端消息 id：本地消息本身没有 id，不取回来就没法删除单条对话。
      // preserveLocalIds 让刚发出的这两条沿用本地 id，避免整屏重放入场动画。
      try {
        await syncMessages(conversationId.value, { preserveLocalIds: true })
      } catch {
        // 取不到就保留本地视图，删除按钮会自动隐藏
      }
    }
  }

  function stop() {
    if (controller) controller.abort()
  }

  return {
    messages,
    sending,
    modelId,
    conversations,
    favoriteConversations,
    conversationId,
    conversationTitle,
    loadingHistory,
    hasConversation,
    send,
    stop,
    newConversation,
    openConversation,
    deleteConversation,
    clearConversations,
    setFavorite,
    renameFavorite,
    reorderFavorites,
    deleteMessage,
    refreshConversations
  }
}
