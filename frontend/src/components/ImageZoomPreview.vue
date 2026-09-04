<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{
  src: string | null
}>()

const emit = defineEmits<{
  close: []
}>()

const open = computed(() => Boolean(props.src))
const scale = ref(1)
const tx = ref(0)
const ty = ref(0)
const dragging = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)
const panStartX = ref(0)
const panStartY = ref(0)

const transformStyle = computed(() => ({
  transform: `translate(${tx.value}px, ${ty.value}px) scale(${scale.value})`,
}))

const zoomLabel = computed(() => `${Math.round(scale.value * 100)}%`)

function resetZoom() {
  scale.value = 1
  tx.value = 0
  ty.value = 0
}

function setZoom(next: number) {
  scale.value = Math.min(6, Math.max(0.5, next))
}

function close() {
  emit('close')
}

function onBackdropClick() {
  close()
}

function onWheel(event: WheelEvent) {
  if (!open.value) return
  event.preventDefault()
  setZoom(scale.value * (event.deltaY < 0 ? 1.12 : 1 / 1.12))
}

function onMouseDown(event: MouseEvent) {
  if (!open.value) return
  dragging.value = true
  dragStartX.value = event.clientX
  dragStartY.value = event.clientY
  panStartX.value = tx.value
  panStartY.value = ty.value
}

function onMouseMove(event: MouseEvent) {
  if (!dragging.value) return
  tx.value = panStartX.value + (event.clientX - dragStartX.value)
  ty.value = panStartY.value + (event.clientY - dragStartY.value)
}

function stopDrag() {
  dragging.value = false
}

function onDoubleClick(event: MouseEvent) {
  event.preventDefault()
  if (scale.value === 1) setZoom(2.5)
  else resetZoom()
}

function onKeydown(event: KeyboardEvent) {
  if (!open.value) return
  if (event.key === 'Escape') close()
  if (event.key === '+' || event.key === '=') setZoom(scale.value * 1.2)
  if (event.key === '-') setZoom(scale.value / 1.2)
  if (event.key === '0') resetZoom()
}

watch(
  () => props.src,
  (value) => {
    resetZoom()
    document.body.style.overflow = value ? 'hidden' : ''
  },
)

window.addEventListener('keydown', onKeydown)
window.addEventListener('mousemove', onMouseMove)
window.addEventListener('mouseup', stopDrag)

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', stopDrag)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="image-zoom-preview">
      <div class="image-zoom-preview__backdrop" @click="onBackdropClick" />
      <div class="image-zoom-preview__stage">
        <button type="button" class="image-zoom-preview__close" aria-label="关闭" @click="close">×</button>
        <div class="image-zoom-preview__toolbar">
          <button type="button" title="缩小" @click.stop="setZoom(scale / 1.2)">−</button>
          <span>{{ zoomLabel }}</span>
          <button type="button" title="放大" @click.stop="setZoom(scale * 1.2)">+</button>
          <button type="button" title="重置" @click.stop="resetZoom">重置</button>
        </div>
        <div
          class="image-zoom-preview__viewport"
          :class="{ 'is-dragging': dragging }"
          @wheel.prevent="onWheel"
          @mousedown="onMouseDown"
          @dblclick="onDoubleClick"
        >
          <img :src="src || ''" alt="" draggable="false" :style="transformStyle" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* 2026-09-02 - 答图/商品图预览看不清 - 对齐桌面范例：全屏+缩放拖拽，挂 body 防被门户裁切 */
.image-zoom-preview {
  position: fixed;
  inset: 0;
  z-index: 3000;
}
.image-zoom-preview__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(7, 22, 45, 0.78);
  backdrop-filter: blur(2px);
}
.image-zoom-preview__stage {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
}
.image-zoom-preview__close {
  position: absolute;
  top: 14px;
  right: 16px;
  z-index: 4;
  width: 40px;
  height: 40px;
  border: 0;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  color: #12325a;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
}
.image-zoom-preview__toolbar {
  position: absolute;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 4;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
}
.image-zoom-preview__toolbar button {
  min-width: 32px;
  height: 32px;
  border: 1px solid #d9e8f6;
  border-radius: 8px;
  background: #fff;
  color: #12325a;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
}
.image-zoom-preview__toolbar button:hover {
  background: #eef5fd;
  color: #2d6cdf;
}
.image-zoom-preview__toolbar span {
  min-width: 52px;
  text-align: center;
  font-size: 12px;
  font-weight: 700;
  color: #58708f;
}
.image-zoom-preview__viewport {
  position: absolute;
  inset: 0;
  z-index: 2;
  overflow: hidden;
  cursor: grab;
  touch-action: none;
  display: flex;
  align-items: center;
  justify-content: center;
}
.image-zoom-preview__viewport.is-dragging {
  cursor: grabbing;
}
.image-zoom-preview__viewport img {
  max-width: none;
  max-height: none;
  transform-origin: center center;
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
  user-select: none;
}
</style>
