<script setup>
import { computed, ref } from 'vue'
import { conversationLabel as label } from '../composables/useChat'

const props = defineProps({
  conversations: { type: Array, default: () => [] },
  activeId: { type: [Number, String, null], default: null },
  emptyText: { type: String, default: '还没有历史会话' }
})
const emit = defineEmits(['select', 'delete', 'favorite', 'rename', 'reorder'])

const DAY = 24 * 60 * 60 * 1000

function startOfDay(ts) {
  const d = new Date(ts)
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

// 收藏会话始终置顶，顺序即后端的 favorite_order（可拖拽调整）
const favorites = computed(() => props.conversations.filter((c) => c.favorite))

// 其余会话按 updatedAt 本地日期分组：今天 / 昨天 / 更早
const groups = computed(() => {
  const todayStart = startOfDay(Date.now())
  const yesterdayStart = todayStart - DAY
  const buckets = { today: [], yesterday: [], earlier: [] }
  for (const c of props.conversations) {
    if (c.favorite) continue
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

const isActive = (c) => String(c.id) === String(props.activeId)

// ---- 备注名：就地编辑，只改展示名，不动会话标题 ----
const renamingId = ref(null)
const renameDraft = ref('')
let renameCancelled = false

function startRename(conv) {
  renameCancelled = false
  renamingId.value = conv.id
  renameDraft.value = conv.favoriteNote || ''
}

function commitRename(conv) {
  if (renamingId.value == null) return
  if (renameCancelled) {
    renameCancelled = false
    renamingId.value = null
    return
  }
  const note = renameDraft.value.trim()
  renamingId.value = null
  if (note === (conv.favoriteNote || '')) return
  emit('rename', { conversation: conv, note })
}

function cancelRename() {
  renameCancelled = true
  renamingId.value = null
}

const focusInput = (el) => el?.focus()

// ---- 收藏区拖拽排序（原生 HTML5 DnD，只在收藏分组内生效）----
const dragIndex = ref(-1)
const overIndex = ref(-1)

function onDragStart(index, event) {
  dragIndex.value = index
  overIndex.value = index
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    // Firefox 必须 setData 才会真正开始拖拽
    event.dataTransfer.setData('text/plain', String(index))
  }
}

function onDragOver(index, event) {
  if (dragIndex.value < 0) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  overIndex.value = index
}

function onDrop(index) {
  const from = dragIndex.value
  resetDrag()
  if (from < 0 || from === index) return
  const ids = favorites.value.map((c) => c.id)
  const [moved] = ids.splice(from, 1)
  ids.splice(index, 0, moved)
  emit('reorder', ids)
}

function resetDrag() {
  dragIndex.value = -1
  overIndex.value = -1
}
</script>

<template>
  <div class="conv-list">
    <template v-if="conversations.length">
      <section v-if="favorites.length" class="conv-group">
        <div class="conv-group-label">★ 收藏</div>
        <div
          v-for="(c, index) in favorites"
          :key="c.id"
          class="conv-row fav"
          :class="{
            active: isActive(c),
            dragging: dragIndex === index,
            'drop-target': dragIndex >= 0 && overIndex === index && dragIndex !== index
          }"
          :draggable="renamingId !== c.id"
          @dragstart="onDragStart(index, $event)"
          @dragover="onDragOver(index, $event)"
          @drop.prevent="onDrop(index)"
          @dragend="resetDrag"
        >
          <template v-if="renamingId === c.id">
            <input
              :ref="focusInput"
              v-model="renameDraft"
              class="conv-rename-input"
              maxlength="120"
              placeholder="给这个会话起个好记的名字"
              @keydown.enter.prevent="commitRename(c)"
              @keydown.esc.prevent="cancelRename"
              @blur="commitRename(c)"
            />
          </template>
          <template v-else>
            <button
              type="button"
              class="conv-item"
              :title="label(c)"
              @click="$emit('select', c)"
            >
              <span class="conv-item-ic star">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="m12 3.6 2.6 5.4 5.9.8-4.3 4.1 1.1 5.9L12 17l-5.3 2.8 1.1-5.9-4.3-4.1 5.9-.8L12 3.6Z" />
                </svg>
              </span>
              <span class="conv-item-title">{{ label(c) }}</span>
            </button>
            <button
              type="button"
              class="conv-action conv-rename"
              title="设置备注名"
              :aria-label="`设置备注名 ${label(c)}`"
              @click.stop="startRename(c)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M4 20h4l10-10-4-4L4 16v4Z" /><path d="m14 6 4 4" />
              </svg>
            </button>
            <button
              type="button"
              class="conv-action conv-star on"
              title="取消收藏"
              :aria-label="`取消收藏 ${label(c)}`"
              @click.stop="$emit('favorite', { conversation: c, favorite: false })"
            >
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="m12 3.6 2.6 5.4 5.9.8-4.3 4.1 1.1 5.9L12 17l-5.3 2.8 1.1-5.9-4.3-4.1 5.9-.8L12 3.6Z" />
              </svg>
            </button>
            <button
              type="button"
              class="conv-action conv-delete"
              :aria-label="`删除会话 ${label(c)}`"
              title="删除会话"
              @click.stop="$emit('delete', c)"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
              </svg>
            </button>
          </template>
        </div>
      </section>

      <section v-for="g in groups" :key="g.label" class="conv-group">
        <div class="conv-group-label">{{ g.label }}</div>
        <div
          v-for="c in g.items"
          :key="c.id"
          class="conv-row"
          :class="{ active: isActive(c) }"
        >
          <button
            type="button"
            class="conv-item"
            :title="label(c)"
            @click="$emit('select', c)"
          >
            <span class="conv-item-ic">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M5 5h14v11H9l-4 4V5Z" />
              </svg>
            </span>
            <span class="conv-item-title">{{ label(c) }}</span>
          </button>
          <button
            type="button"
            class="conv-action conv-star"
            title="收藏这个会话"
            :aria-label="`收藏会话 ${label(c)}`"
            @click.stop="$emit('favorite', { conversation: c, favorite: true })"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="m12 3.6 2.6 5.4 5.9.8-4.3 4.1 1.1 5.9L12 17l-5.3 2.8 1.1-5.9-4.3-4.1 5.9-.8L12 3.6Z" />
            </svg>
          </button>
          <button
            type="button"
            class="conv-action conv-delete"
            :aria-label="`删除会话 ${label(c)}`"
            title="删除会话"
            @click.stop="$emit('delete', c)"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
            </svg>
          </button>
        </div>
      </section>
    </template>
    <p v-else class="conv-empty">{{ emptyText }}</p>
  </div>
</template>
