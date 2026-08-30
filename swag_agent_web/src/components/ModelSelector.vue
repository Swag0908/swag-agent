<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  modelId: { type: Number, required: true },
  models: { type: Array, required: true }
})
const emit = defineEmits(['select'])

const open = ref(false)
const root = ref(null)

const current = computed(
  () => props.models.find((m) => m.id === props.modelId) || props.models[0]
)

function toggle() {
  open.value = !open.value
}

function choose(m) {
  emit('select', m.id)
  open.value = false
}

function onDocClick(e) {
  if (root.value && !root.value.contains(e.target)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="root" class="model-select">
    <button class="model-trigger" type="button" @click="toggle">
      <span class="model-dot"></span>
      <span>{{ current?.name || '选择模型' }}</span>
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    <div v-if="open" class="model-menu">
      <button
        v-for="m in models"
        :key="m.id"
        type="button"
        class="model-item"
        :class="{ active: m.id === modelId }"
        @click="choose(m)"
      >
        <div class="model-item-main">
          <div class="model-item-name">{{ m.name }}</div>
          <div class="model-item-desc">{{ m.desc }}</div>
        </div>
        <span v-if="m.id === modelId" class="model-item-check">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M20 6 9 17l-5-5" />
          </svg>
        </span>
      </button>
    </div>
  </div>
</template>
