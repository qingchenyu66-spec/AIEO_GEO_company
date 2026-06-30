<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  values: Array<number | null | undefined>
  width?: number
  height?: number
  lowerIsBetter?: boolean
  stroke?: string
  tone?: 'light' | 'dark'
  showArea?: boolean
}>(), {
  width: 92,
  height: 28,
  lowerIsBetter: false,
  stroke: '#2d6cdf',
  tone: 'dark',
  showArea: false,
})

const strokeColor = computed(() => {
  if (props.tone === 'light') {
    if (trendClass.value === 'up') return '#6dffc8'
    if (trendClass.value === 'down') return '#ff9cab'
    return '#9fd4ff'
  }
  return props.stroke
})

const hasSeries = computed(() => props.values.some(value => value !== null && value !== undefined))

const chartPoints = computed(() => {
  const series = props.values.map(value => (value === null || value === undefined ? null : Number(value)))
  const valid = series.filter((value): value is number => value !== null && !Number.isNaN(value))
  if (valid.length < 2) return [] as Array<[number, number]>

  const min = Math.min(...valid)
  const max = Math.max(...valid)
  const range = max - min || 1
  const stepX = props.width / Math.max(series.length - 1, 1)

  const points: Array<[number, number]> = []
  series.forEach((value, index) => {
    if (value === null || Number.isNaN(value)) return
    const x = index * stepX
    const normalized = (value - min) / range
    const y = props.height - normalized * (props.height - 4) - 2
    points.push([x, y])
  })
  return points
})

const path = computed(() => {
  if (chartPoints.value.length < 2) return ''
  return chartPoints.value.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
})

const areaPath = computed(() => {
  if (!props.showArea || chartPoints.value.length < 2) return ''
  const first = chartPoints.value[0]
  const last = chartPoints.value[chartPoints.value.length - 1]
  const line = chartPoints.value.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
  return `${line} L ${last[0].toFixed(1)} ${props.height} L ${first[0].toFixed(1)} ${props.height} Z`
})

const trendClass = computed(() => {
  const series = props.values.filter((value): value is number => value !== null && value !== undefined && !Number.isNaN(Number(value)))
  if (series.length < 2) return ''
  const delta = series[series.length - 1] - series[0]
  if (Math.abs(delta) < 0.05) return 'flat'
  const improved = props.lowerIsBetter ? delta < 0 : delta > 0
  return improved ? 'up' : 'down'
})

const gradientId = computed(() => `ws-fill-${Math.random().toString(36).slice(2, 9)}`)
</script>

<template>
  <svg
    v-if="hasSeries && path"
    class="workspace-sparkline"
    :class="[trendClass, `tone-${tone}`]"
    :width="width"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    <defs>
      <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="strokeColor" stop-opacity="0.34" />
        <stop offset="100%" :stop-color="strokeColor" stop-opacity="0" />
      </linearGradient>
    </defs>
    <path v-if="areaPath" class="workspace-sparkline-area" :d="areaPath" :fill="`url(#${gradientId})`" />
    <path :d="path" fill="none" :stroke="strokeColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</template>
