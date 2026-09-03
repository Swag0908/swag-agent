<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps({
  message: { type: Object, required: true }
})

// 助手回复按 Markdown 渲染（经 DOMPurify 消毒，防 XSS）
const rendered = computed(() => {
  if (props.message.role !== 'assistant' || !props.message.content) return ''
  const html = marked.parse(props.message.content, { gfm: true, breaks: true })
  return DOMPurify.sanitize(html)
})
</script>

<template>
  <div class="msg" :class="message.role">
    <div class="msg-avatar" aria-hidden="true">
      <img v-if="message.role === 'assistant'" src="/brand/cowhorse-glyph-256.png" alt="" />
      <svg
        v-else
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    </div>

    <div class="bubble">
      <template v-if="message.role === 'assistant'">
        <div v-if="message.content" class="markdown" v-html="rendered"></div>
        <span v-if="message.streaming && !message.content" class="typing">
          <span></span><span></span><span></span>
        </span>
        <span v-else-if="message.streaming" class="caret"></span>
      </template>
      <div v-else class="text">{{ message.content }}</div>
    </div>
  </div>
</template>
