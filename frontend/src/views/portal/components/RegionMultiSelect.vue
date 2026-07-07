<script setup lang="ts">
import { Search, X } from '@lucide/vue'
import { computed, ref } from 'vue'
import { filterRegionOptions, regionLabel } from '../regionOptions'

const props = withDefaults(defineProps<{
  modelValue: string[]
  disabled?: boolean
  placeholder?: string
}>(), {
  disabled: false,
  placeholder: '不选则代表全部区域',
})

const emit = defineEmits<{
  'update:modelValue': [string[]]
}>()

const searchQuery = ref('')
const filteredRegions = computed(() => filterRegionOptions(searchQuery.value))

function toggleRegion(code: string) {
  if (props.disabled) return
  const selected = props.modelValue.includes(code)
  emit(
    'update:modelValue',
    selected ? props.modelValue.filter(item => item !== code) : [...props.modelValue, code],
  )
}

function removeRegion(code: string) {
  if (props.disabled) return
  emit('update:modelValue', props.modelValue.filter(item => item !== code))
}

function clearSearch() {
  searchQuery.value = ''
}
</script>

<template>
  <div class="region-multi-select" :class="{ 'is-disabled': disabled }">
    <div v-if="!disabled" class="region-multi-select-search">
      <Search :size="15" aria-hidden="true" />
      <input
        v-model="searchQuery"
        type="search"
        autocomplete="off"
        placeholder="搜索省份名称或拼音，如：广东、gd、四川"
      />
      <button v-if="searchQuery" type="button" class="region-search-clear" aria-label="清空搜索" @click="clearSearch">
        <X :size="14" />
      </button>
    </div>

    <div v-if="modelValue.length" class="region-multi-select-tags">
      <span v-for="code in modelValue" :key="code" class="region-tag">
        {{ regionLabel(code) }}
        <button v-if="!disabled" type="button" class="region-tag-remove" aria-label="移除" @click="removeRegion(code)">
          <X :size="12" />
        </button>
      </span>
    </div>
    <p v-else-if="disabled" class="region-multi-select-empty-hint">全部区域</p>

    <p v-if="!disabled" class="region-multi-select-hint">
      {{ placeholder }} · 已选 {{ modelValue.length }} 个
      <template v-if="searchQuery.trim()"> · 匹配 {{ filteredRegions.length }} 个</template>
    </p>

    <div v-if="!disabled" class="region-multi-select-panel">
      <div v-if="!filteredRegions.length" class="region-multi-select-empty">无匹配省份，请换个关键词</div>
      <button
        v-for="region in filteredRegions"
        :key="region.code"
        type="button"
        class="region-option-btn"
        :class="{ selected: modelValue.includes(region.code) }"
        @click="toggleRegion(region.code)"
      >
        {{ region.name }}
      </button>
    </div>
  </div>
</template>
