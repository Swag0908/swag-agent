<script setup>
import { computed } from 'vue'

const props = defineProps({
  conversations: { type: Array, default: () => [] },
  activeId: { type: [Number, String, null], default: null },
  emptyText: { type: String, default: '还没有历史会话' }
})
defineEmits(['select'])

const DAY = 24 * 60 * 60 * 1000

function startOfDay(ts) {
  const d = new Date(ts)
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

// 按 updatedAt 本地日期分组：今天 / 昨天 / 更早
const groups = computed(() => {
  const todayStart = startOfDay(Date.now())
  const yesterdayStart = todayStart - DAY
  const buckets = { today: [], yesterday: [], earlier: [] }
  for (const c of props.conversations) {
    const ts = Number(c.updatedAtMs || c.createdAtMs || Date.now())
    const start = startOfDay(ts)
    if (start >= todayStart) buckets.today.push(c)
    else if (start >= yesterdayStart) buckets.yesterday.push(c)
    else buckets.earlier.push(c)
  }
  return [
    { label: '今天', items: buckets.today },
    { label: '昨天', items: buckets.yesterday },
    { label: '更早', items: buckets.earlier }
  ].filter((g) => g.items.length)
})
</script>

<template>
  <div class="conv-list">
    <template v-if="groups.length">
      <section v-for="g in groups" :key="g.label" class="conv-group">
        <div class="conv-group-label">{{ g.label }}</div>
        <button
          v-for="c in g.items"
          :key="c.id"
          type="button"
          class="conv-item"
          :class="{ active: String(c.id) === String(activeId) }"
          :title="c.title || '新对话'"
          @click="$emit('select', c)"
        >
          <span class="conv-item-ic">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M5 5h14v11H9l-4 4V5Z" />
            </svg>
          </span>
          <span class="conv-item-title">{{ c.title || '新对话' }}</span>
        </button>
      </section>
    </template>
    <p v-else class="conv-empty">{{ emptyText }}</p>
  </div>
</template>
