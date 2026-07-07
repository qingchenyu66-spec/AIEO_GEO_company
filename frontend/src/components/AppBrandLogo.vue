<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'icon' | 'full' | 'stacked'
    alt?: string
  }>(),
  {
    variant: 'icon',
    alt: '艾迪亚控股集团',
  },
)

const srcMap = {
  icon: '/logo-icon.png',
  full: '/logo-full.png',
  stacked: '/logo-stacked.png',
} as const
</script>

<template>
  <img
    :src="srcMap[variant]"
    :alt="alt"
    class="app-brand-logo"
    :class="`app-brand-logo--${variant}`"
    decoding="async"
  />
</template>
