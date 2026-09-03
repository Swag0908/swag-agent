<script setup>
defineEmits(['select'])

const prompts = [
  { index: '01', title: '规划今日任务', prompt: '帮我规划今天的待办事项，并按优先级排序' },
  { index: '02', title: '梳理复杂问题', prompt: '我有一个复杂问题，请帮我拆解成可执行的步骤' },
  { index: '03', title: '起草专业内容', prompt: '帮我写一份简洁、专业、有说服力的产品文案' },
  { index: '04', title: '查询与总结', prompt: '向我介绍你能帮我完成哪些工作' }
]
</script>

<template>
  <div class="empty">
    <div class="empty-kicker"><span></span>COWHOURSE INTELLIGENCE</div>
    <div class="empty-hero">
      <div class="empty-orb" aria-hidden="true">
        <img src="/brand/cowhorse-glyph-256.png" alt="" />
      </div>
      <div class="empty-copy">
        <h1 class="empty-title">成为牛马传奇<span class="title-mark">.</span></h1>
        <p class="empty-sub">
          把想法变成行动，把琐事变成结果。<br />
          Cowhourse Legend 会记录、思考并协助你持续完成真实任务。
        </p>
      </div>
    </div>
    <div class="empty-divider"><span>从一个任务开始</span></div>
    <div class="prompts">
      <button
        v-for="item in prompts"
        :key="item.index"
        class="prompt-card"
        type="button"
        @click="$emit('select', item.prompt)"
      >
        <span class="prompt-index">{{ item.index }}</span>
        <span class="prompt-title">{{ item.title }}</span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </button>
    </div>
  </div>
</template>
