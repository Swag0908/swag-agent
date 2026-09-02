import { reactive, ref, watch } from 'vue'
import { streamChat } from '../api/chat'

let idSeq = 0
const nextId = () => ++idSeq

const MODEL_STORAGE_KEY = 'swagAgent.model'

// 后端 SelectModelTool 支持 id 1（V4 Flash）与 2（V4 Pro），默认 1
function storedModelId() {
  const v = Number(localStorage.getItem(MODEL_STORAGE_KEY))
  return v === 1 || v === 2 ? v : 1
}

export function useChat() {
  const messages = reactive([])
  const sending = ref(false)
  const modelId = ref(storedModelId())

  // 记住用户的选择，下次打开仍是上次选的模型
  watch(modelId, (v) => localStorage.setItem(MODEL_STORAGE_KEY, String(v)))

  let controller = null

  async function send(raw) {
    const text = String(raw ?? '').trim()
    if (!text || sending.value) return

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
    }
  }

  function stop() {
    if (controller) controller.abort()
  }

  function clear() {
    stop()
    messages.splice(0, messages.length)
  }

  return { messages, sending, modelId, send, stop, clear }
}
