<script setup>
import { ref } from 'vue'

const props = defineProps({
  sending: { type: Boolean, default: false }
})
const emit = defineEmits(['send', 'stop'])

const text = ref('')
const ta = ref(null)

function autosize() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function submit() {
  const v = text.value.trim()
  if (!v) return
  if (props.sending) {
    emit('stop')
    return
  }
  emit('send', v)
  text.value = ''
  autosize()
}

function onKeydown(e) {
  // isComposing：中文输入法组词阶段按回车不发送
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}

defineExpose({ focus: () => ta.value?.focus() })
</script>

<template>
  <div class="composer-box">
    <textarea
      ref="ta"
      v-model="text"
      class="composer-input"
      rows="1"
      placeholder="给 SWAG Agent 发消息…"
      @keydown="onKeydown"
      @input="autosize"
    ></textarea>
    <button
      type="button"
      class="send-btn"
      :class="{ stop: sending }"
      :disabled="!sending && !text.trim()"
      :title="sending ? '停止生成' : '发送'"
      @click="submit"
    >
      <svg
        v-if="!sending"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M22 2 11 13" />
        <path d="M22 2 15 22l-4-9-9-4 20-7z" />
      </svg>
      <svg v-else viewBox="0 0 24 24" fill="currentColor">
        <rect x="6" y="6" width="12" height="12" rx="2" />
      </svg>
    </button>
  </div>
</template>
