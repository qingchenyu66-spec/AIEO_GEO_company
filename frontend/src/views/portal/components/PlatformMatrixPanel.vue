<script setup lang="ts">
import { computed, ref } from 'vue'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import { platformAccentColor } from '../platformMeta'
import type { PlatformMatrix } from '../../../services/platforms'
import { formatDateTime } from '../portalUtils'

const props = defineProps<{
  matrix: PlatformMatrix | null
  loading?: boolean
}>()

const emit = defineEmits<{ refresh: [] }>()

const activeFilter = ref<'all' | 'healthy' | 'checking' | 'issue'>('all')

const filteredPlatforms = computed(() => {
  const rows = props.matrix?.platforms || []
  if (activeFilter.value === 'healthy') return rows.filter(item => item.status === 'healthy')
  if (activeFilter.value === 'checking') return rows.filter(item => item.status === 'checking' || item.status === 'pending')
  if (activeFilter.value === 'issue') return rows.filter(item => item.status === 'degraded' || item.status === 'down')
  return rows
})

const filterOptions = computed(() => [
  { key: 'all' as const, label: `全部 ${props.matrix?.supported_count ?? 0}` },
  { key: 'healthy' as const, label: `正常 ${props.matrix?.healthy_count ?? 0}` },
  { key: 'checking' as const, label: `验证中 ${(props.matrix?.checking_count ?? 0) + (props.matrix?.pending_count ?? 0)}` },
  { key: 'issue' as const, label: `异常 ${props.matrix?.issue_count ?? 0}` },
])
</script>

<template>
  <section class="platform-matrix-panel">
    <div class="platform-matrix-hero">
      <div class="platform-matrix-kpi platform-matrix-balance">
        <span>模力账户余额</span>
        <b v-if="matrix?.molizhishu_balance?.available">¥ {{ matrix.molizhishu_balance.current_balance_text }}</b>
        <b v-else class="is-muted">--</b>
        <em v-if="matrix?.molizhishu_balance?.fetched_at">更新 {{ formatDateTime(matrix.molizhishu_balance.fetched_at) }}</em>
        <em v-else-if="matrix?.molizhishu_balance?.error" class="is-error">{{ matrix.molizhishu_balance.error }}</em>
        <em v-else>模力指数账户可用余额</em>
      </div>
      <div class="platform-matrix-kpi">
        <span>支持平台</span>
        <b>{{ matrix?.supported_count ?? 0 }}</b>
        <em>模力指数可接入目录</em>
      </div>
      <div class="platform-matrix-kpi">
        <span>服务正常</span>
        <b>{{ matrix?.healthy_count ?? 0 }}</b>
        <em>今日探测通过</em>
      </div>
      <div class="platform-matrix-kpi">
        <span>验证中</span>
        <b>{{ (matrix?.checking_count ?? 0) + (matrix?.pending_count ?? 0) }}</b>
        <em>待验证或探测进行中</em>
      </div>
      <div class="platform-matrix-kpi">
        <span>服务异常</span>
        <b>{{ matrix?.issue_count ?? 0 }}</b>
        <em>失败或部分失败</em>
      </div>
    </div>

    <div class="platform-matrix-toolbar">
      <div class="platform-matrix-filters">
        <button
          v-for="item in filterOptions"
          :key="item.key"
          type="button"
          :class="{ active: activeFilter === item.key }"
          @click="activeFilter = item.key"
        >
          {{ item.label }}
        </button>
      </div>
      <div class="platform-matrix-meta">
        <span v-if="matrix?.catalog_source_url">平台目录来源：<a :href="matrix.catalog_source_url" target="_blank" rel="noreferrer">模力指数官方文档</a></span>
        <span v-if="matrix?.catalog_fetched_at"> · 同步 {{ formatDateTime(matrix.catalog_fetched_at) }}</span>
        <span v-if="matrix?.first_schedule_at"> · 今日首轮检测 {{ formatDateTime(matrix.first_schedule_at) }}</span>
        <button type="button" class="ghost-link-btn" :disabled="loading" @click="emit('refresh')">
          {{ loading ? '刷新中...' : '立即刷新' }}
        </button>
      </div>
    </div>

    <div v-if="loading && !matrix" class="platform-matrix-empty">平台服务状态加载中...</div>
    <div v-else-if="filteredPlatforms.length" class="platform-matrix-grid">
      <article
        v-for="item in filteredPlatforms"
        :key="item.code"
        class="platform-matrix-card"
        :style="{ '--accent': platformAccentColor(item.code) }"
      >
        <div class="platform-matrix-card-head">
          <div class="platform-matrix-card-title">
            <PlatformBadge :code="item.code" size="md" icon-only />
            <div>
              <b>{{ item.name }}</b>
              <small>{{ item.channel_label }} · {{ item.code }}</small>
            </div>
          </div>
          <span class="platform-matrix-status" :class="item.status">{{ item.status_label }}</span>
        </div>

        <p class="platform-matrix-hint">{{ item.status_hint }}</p>

        <div class="platform-matrix-metrics">
          <div>
            <span>今日探测</span>
            <strong>{{ item.probe_total }}</strong>
          </div>
          <div>
            <span>成功 / 失败</span>
            <strong>{{ item.probe_success }} / {{ item.probe_failed }}</strong>
          </div>
        </div>
      </article>
    </div>
    <div v-else class="platform-matrix-empty">暂无符合条件的平台。</div>
  </section>
</template>
