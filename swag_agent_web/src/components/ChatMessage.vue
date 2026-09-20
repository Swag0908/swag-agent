<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps({
  message: { type: Object, required: true },
  // 只有已经落库的消息才能删（本地占位消息还没有服务端 id）
  deletable: { type: Boolean, default: false }
})
defineEmits(['delete'])

const canDelete = computed(
  () => props.deletable && !props.message.streaming && props.message.serverId != null
)

// 助手回复按 Markdown 渲染（经 DOMPurify 消毒，防 XSS）
const rendered = computed(() => {
  if (props.message.role !== 'assistant' || !props.message.content) return ''
  const html = marked.parse(props.message.content, { gfm: true, breaks: true })
  return DOMPurify.sanitize(html)
})

// ---- 干活过程：让用户看得见「它在做什么」（P0-1）----
// 数据全部来自后端推送的 tool_call 事件；耗时用后端给的真实值，前端不做估算。
const liveTool = computed(() =>
  props.message.role === 'assistant' ? props.message.activeTool : null
)
const isThinking = computed(
  () => props.message.role === 'assistant' && props.message.thinking && !liveTool.value
)
// 已经跑完的工具（含失败）：正文输出期间也保留，方便回看「它干了什么」
const finishedTools = computed(() =>
  (props.message.tools || []).filter((tool) => tool.status !== 'running')
)
const reasoning = computed(() => (props.message.reasoning || '').trim())
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
        <!-- 工具调用前后的铺垫文字：只展示，不进正文、不落库。
             正文一旦出现就收起它——工具之后那段文字会被后端转正为最终回答，
             否则同一段话会在「思考过程」和正文里各显示一遍。 -->
        <details v-if="reasoning && !message.content" class="thinking-block">
          <summary>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M12 3a6 6 0 0 0-3.5 10.9V17h7v-3.1A6 6 0 0 0 12 3Z" />
              <path d="M10 20h4" />
            </svg>
            <span>思考过程</span>
          </summary>
          <div class="thinking-body">{{ reasoning }}</div>
        </details>

        <!-- 正在干活：工具名 + 参数摘要，让用户知道它没死机 -->
        <div v-if="liveTool" class="agent-status">
          <span class="tool-spinner" aria-hidden="true"></span>
          <span class="agent-status-text">{{ liveTool.display || '正在调用工具…' }}</span>
          <span class="agent-status-time">进行中</span>
        </div>
        <div v-else-if="isThinking" class="agent-status thinking">
          <span class="tool-dots" aria-hidden="true"><span></span><span></span><span></span></span>
          <span class="agent-status-text">正在思考…</span>
        </div>

        <div v-if="message.content" class="markdown" v-html="rendered"></div>
        <span v-if="message.streaming && !message.content && !liveTool && !isThinking" class="typing">
          <span></span><span></span><span></span>
        </span>
        <span v-else-if="message.streaming && message.content" class="caret"></span>

        <!-- 这一轮用过哪些工具：一目了然的「工作记录」 -->
        <div v-if="finishedTools.length" class="tool-history">
          <span
            v-for="tool in finishedTools"
            :key="tool.key"
            class="tool-chip"
            :class="tool.status"
            :title="tool.name + (tool.detail ? ' · ' + tool.detail : '')"
          >
            <svg
              v-if="tool.status === 'done'"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.2"
            >
              <path d="m5 13 4 4L19 7" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 8v5M12 16h.01" />
            </svg>
            <span>{{ tool.name }}</span>
          </span>
        </div>
      </template>
      <div v-else class="text">{{ message.content }}</div>
    </div>

    <button
      v-if="canDelete"
      type="button"
      class="msg-delete"
      title="删除这条对话（提问与配对的回答会一起删除，模型也会忘掉）"
      aria-label="删除这条对话"
      @click="$emit('delete', message)"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
      </svg>
    </button>
  </div>
</template>
