<script setup lang="ts">
import { computed, ref } from 'vue'
import { getPlatformMeta } from '../views/portal/platformMeta'

const props = withDefaults(defineProps<{
  code: string
  size?: 'xs' | 'sm' | 'md' | 'lg'
  showLabel?: boolean
  iconOnly?: boolean
  label?: string
}>(), {
  size: 'sm',
  showLabel: true,
  iconOnly: false,
})

const meta = computed(() => getPlatformMeta(props.code))
const displayLabel = computed(() => props.label || meta.value.name)
const iconFailed = ref(false)

function onIconError() {
  iconFailed.value = true
}
</script>

<template>
  <span
    class="platform-badge"
    :class="[`platform-badge--${size}`, { 'platform-badge--icon-only': iconOnly || !showLabel }]"
    :title="displayLabel"
  >
    <span
      v-if="!meta.icon || iconFailed"
      class="platform-badge__fallback"
      :style="{ background: meta.accent }"
      aria-hidden="true"
    >
      {{ displayLabel.trim().slice(0, 1) }}
    </span>
    <img
      v-else
      class="platform-badge__icon"
      :src="meta.icon"
      :alt="displayLabel"
      :loading="iconOnly ? 'eager' : 'lazy'"
      decoding="async"
      @error="onIconError"
    />
    <span v-if="showLabel && !iconOnly" class="platform-badge__label">{{ displayLabel }}</span>
  </span>
</template>
