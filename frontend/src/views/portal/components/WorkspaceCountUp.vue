<script setup lang="ts">
import { computed, toRef, watch } from 'vue'
import { useCountUp } from '../../../composables/useCountUp'

const props = withDefaults(defineProps<{
  value: number | null | undefined
  duration?: number
  decimals?: number
  emptyText?: string
  active?: boolean
  generation?: number
}>(), {
  duration: 1200,
  decimals: 0,
  emptyText: '-',
  active: true,
  generation: 0,
})

const valueRef = toRef(props, 'value')

const { display, restart } = useCountUp(
  () => valueRef.value,
  {
    duration: props.duration,
    decimals: props.decimals,
    enabled: () => props.active,
  },
)

watch(() => props.generation, () => {
  restart()
})

const formatted = computed(() => {
  if (props.value === null || props.value === undefined) return props.emptyText
  if (props.decimals > 0) return display.value.toFixed(props.decimals)
  return String(Math.round(display.value))
})
</script>

<template>
  <span class="workspace-count-up">{{ formatted }}</span>
</template>
