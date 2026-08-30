<script setup>
defineEmits(['select'])

const prompts = [
  '介绍一下你自己',
  '用一句话解释什么是 AI Agent',
  '帮我写一段产品介绍文案',
  '现在几点了？'
]
</script>

<template>
  <div class="empty">
    <div class="empty-orb">
      <svg viewBox="0 0 24 24" fill="currentColor">
        <path
          d="M12 2.5l2.1 6.4 6.4 2.1-6.4 2.1L12 19.5l-2.1-6.4L3.5 11l6.4-2.1L12 2.5z"
        />
        <path
          d="M19 3l.7 2.3L22 6l-2.3.7L19 9l-.7-2.3L16 6l2.3-.7L19 3z"
          opacity=".7"
        />
      </svg>
    </div>
    <h2 class="empty-title">你好，我是 SWAG Agent</h2>
    <p class="empty-sub">
      基于 DeepSeek 的智能助手。在下方输入你的问题，我会以流式方式逐字回复。
    </p>
    <div class="prompts">
      <button
        v-for="p in prompts"
        :key="p"
        class="prompt-chip"
        @click="$emit('select', p)"
      >
        {{ p }}
      </button>
    </div>
  </div>
</template>
