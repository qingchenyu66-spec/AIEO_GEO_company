<script setup lang="ts">
import { ref } from 'vue'
import { TENANT_LOGO_ACCEPT, TENANT_LOGO_HINT } from '../constants/tenantLogo'

defineProps<{
  previewSrc?: string
  fileName?: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  pick: [event: Event]
  clear: []
}>()

const inputRef = ref<HTMLInputElement | null>(null)

function openPicker() {
  if (inputRef.value) inputRef.value.click()
}
</script>

<template>
  <div class="tenant-logo-field">
    <div class="tenant-logo-field__row">
      <div v-if="previewSrc" class="tenant-logo-field__preview">
        <img :src="previewSrc" alt="" />
      </div>
      <div class="tenant-logo-field__actions">
        <input
          ref="inputRef"
          type="file"
          class="tenant-logo-field__input"
          :accept="TENANT_LOGO_ACCEPT"
          :disabled="disabled"
          @change="emit('pick', $event)"
        />
        <button type="button" class="filter-search-btn tenant-logo-field__pick" :disabled="disabled" @click="openPicker">
          {{ previewSrc || fileName ? '更换图片' : '选择图片' }}
        </button>
        <button
          v-if="fileName"
          type="button"
          class="plain-btn tenant-logo-field__clear"
          :disabled="disabled"
          @click="emit('clear')"
        >
          清除所选
        </button>
        <p v-if="fileName" class="tenant-logo-field__name">{{ fileName }}</p>
      </div>
    </div>
    <p class="tenant-logo-field__hint">{{ TENANT_LOGO_HINT }}</p>
  </div>
</template>

<style scoped>
.tenant-logo-field__row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.tenant-logo-field__preview {
  flex: 0 0 64px;
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
  border: 1px solid var(--portal-chrome-border, #dbe3ef);
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}

.tenant-logo-field__preview img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.tenant-logo-field__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tenant-logo-field__input {
  display: none;
}

.tenant-logo-field__pick {
  margin: 0;
}

.tenant-logo-field__clear {
  margin: 0;
}

.tenant-logo-field__name {
  flex: 1 1 100%;
  margin: 0;
  font-size: 12px;
  color: var(--portal-chrome-muted, #64748b);
  word-break: break-all;
}

.tenant-logo-field__hint {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--portal-chrome-muted, #64748b);
}
</style>
