<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'icon' | 'full' | 'stacked'
    alt?: string
    src?: string
  }>(),
  {
    variant: 'icon',
    alt: '亦智广告',
    src: '',
  },
)

// 2026-08-20 - 方标改亦智矢量 SVG，小尺寸仍清晰；full/stacked 暂仍旧资源
const srcMap = {
  icon: '/logo-yizhi-icon.svg',
  full: '/logo-full.png',
  stacked: '/logo-stacked.png',
} as const

const resolvedSrc = computed(() => props.src || srcMap[props.variant])
</script>

<template>
  <img
    :src="resolvedSrc"
    :alt="alt"
    class="app-brand-logo"
    :class="`app-brand-logo--${variant}`"
    decoding="async"
  />
</template>
