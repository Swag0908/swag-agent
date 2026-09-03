<script setup>
import { ref } from 'vue'

const props = defineProps({ sending: { type: Boolean, default: false } })
const emit = defineEmits(['send', 'stop'])
const text = ref('')
const ta = ref(null)

function autosize() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 180) + 'px'
}

function submit() {
  const value = text.value.trim()
  if (!value) return
  if (props.sending) {
    emit('stop')
    return
  }
  emit('send', value)
  text.value = ''
  autosize()
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
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
      placeholder="描述你想完成的事…"
      @keydown="onKeydown"
      @input="autosize"
    ></textarea>
    <div class="composer-footer">
      <div class="composer-runtime">
        <span class="runtime-dot"></span>
        COWHOURSE CORE
        <span class="composer-shortcut">Enter 发送</span>
      </div>
      <button
        type="button"
        class="send-btn"
        :class="{ stop: sending }"
        :disabled="!sending && !text.trim()"
        :title="sending ? '停止生成' : '发送'"
        @click="submit"
      >
        <svg v-if="!sending" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="currentColor">
          <rect x="7" y="7" width="10" height="10" rx="1.5" />
        </svg>
      </button>
    </div>
  </div>
</template>
