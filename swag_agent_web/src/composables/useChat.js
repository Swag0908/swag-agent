import { reactive, ref, watch, computed } from 'vue'
import { streamChat } from '../api/chat'
import {
  listConversations,
  createConversation,
  getConversationMessages
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

export function useChat() {
  const messages = reactive([])
  const sending = ref(false)
  const modelId = ref(storedModelId())

  // ---- DeepSeek 式工作区：多会话 ----
  const conversations = ref([]) // 服务端返回的历史会话列表
  const conversationId = ref(null) // 当前激活会话（null = 新建会话草稿）
  const conversationTitle = ref('') // 当前会话标题（用于顶栏展示）
  const loadingHistory = ref(false)

  // 记住用户选择的模型，下次打开仍是上次选的模型
  watch(modelId, (v) => localStorage.setItem(MODEL_STORAGE_KEY, String(v)))

  let controller = null

  const hasConversation = computed(() => conversationId.value != null)

  /** 拉取历史会话列表（保持服务端 updated_at 倒序）。 */
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
      const history = await getConversationMessages(conv.id)
      const list = Array.isArray(history) ? history : []
      for (const m of list) {
        messages.push({
          id: nextId(),
          role: m.role === 'user' ? 'user' : 'assistant',
          content: m.content || '',
          streaming: false,
          error: false
        })
      }
    } catch (e) {
      // 会话不存在/已失效：退出该会话状态，回到空白新会话
      conversationId.value = null
      conversationTitle.value = ''
      localStorage.removeItem(ACTIVE_CONVERSATION_KEY)
      messages.push({
        id: nextId(),
        role: 'assistant',
        content: '> ⚠️ 加载历史消息失败：' + (e?.message || '网络错误'),
        streaming: false,
        error: true
      })
    } finally {
      loadingHistory.value = false
    }
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
          createdAtMs: created.createdAtMs,
          updatedAtMs: created.updatedAtMs
        })
      } catch (e) {
        messages.push({
          id: nextId(),
          role: 'assistant',
          content: '> ⚠️ 创建会话失败：' + (e?.message || '网络错误'),
          streaming: false,
          error: true
        })
        return
      }
    }

    messages.push({ id: nextId(), role: 'user', content: text })

    const assistant = reactive({
      id: nextId(),
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
      const cur = conversations.value.find((c) => c.id === conversationId.value)
      if (cur) conversationTitle.value = cur.title || conversationTitle.value
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
    conversationId,
    conversationTitle,
    loadingHistory,
    hasConversation,
    send,
    stop,
    newConversation,
    openConversation,
    refreshConversations
  }
}
