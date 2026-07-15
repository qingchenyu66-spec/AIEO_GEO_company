<script setup lang="ts">
import { computed } from 'vue'
import { RefreshCw } from '@lucide/vue'
import { sortPlatformRows } from '../platformOrder'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import { platformAccentColor } from '../platformMeta'
import type { PlatformMatrix } from '../../../services/platforms'
import { formatDateTime, externalLink } from '../portalUtils'

const props = defineProps<{
  matrix: PlatformMatrix | null
  loading?: boolean
}>()

const emit = defineEmits<{ refresh: [] }>()

const supportedCount = computed(() => props.matrix?.supported_count ?? 0)
const probeTotal = computed(() => props.matrix?.probe_total ?? 0)
const probeSuccess = computed(() => props.matrix?.probe_success ?? 0)
const probeFailed = computed(() => props.matrix?.probe_failed ?? 0)

const metaLine = computed(() => {
  const parts: string[] = []
  if (props.matrix?.catalog_fetched_at) {
    parts.push(`目录同步 ${formatDateTime(props.matrix.catalog_fetched_at)}`)
  }
  if (props.matrix?.first_schedule_at) {
    parts.push(`首轮检测 ${formatDateTime(props.matrix.first_schedule_at)}`)
  }
  if (props.matrix?.updated_at) {
    parts.push(`数据更新 ${formatDateTime(props.matrix.updated_at)}`)
  }
  return parts.join(' · ')
})

const platforms = computed(() => sortPlatformRows(props.matrix?.platforms || []))
const catalogSource = computed(() => props.matrix?.catalog_source || '')
</script>

<template>
  <section class="platform-matrix-panel">
    <header class="platform-matrix-header">
      <div class="platform-matrix-header-top">
        <div class="platform-matrix-summary">
          <strong>今日探测汇总</strong>
          <p>
            共 {{ supportedCount }} 个在架平台 · 探测 {{ probeTotal }} 条
            · 成功 {{ probeSuccess }} 条 · 失败 {{ probeFailed }} 条
            <template v-if="catalogSource"> · 目录源 {{ catalogSource === 'molizhishu_doc' ? '官方文档' : catalogSource }}</template>
          </p>
        </div>
        <div class="platform-matrix-header-actions">
          <p v-if="metaLine" class="platform-matrix-meta-line">{{ metaLine }}</p>
          <a
            v-if="externalLink(matrix?.catalog_source_url)"
            class="platform-matrix-doc-link"
            :href="externalLink(matrix?.catalog_source_url)!"
            target="_blank"
            rel="noopener noreferrer"
          >平台目录文档</a>
          <button type="button" class="platform-matrix-refresh-btn" :disabled="loading" @click="emit('refresh')">
            <RefreshCw :class="{ 'is-spinning': loading }" />
            {{ loading ? '刷新中…' : '刷新数据' }}
          </button>
        </div>
      </div>
    </header>

    <div v-if="loading && !matrix" class="platform-matrix-empty">平台探测数据加载中…</div>
    <div v-else-if="platforms.length" class="platform-matrix-grid">
      <article
        v-for="item in platforms"
        :key="item.code"
        class="platform-matrix-card"
        :class="{
          'is-delisted': (item.labels || []).includes('已下架') || item.catalog_listed === false,
          'is-unavailable': (item.labels || []).includes('无服务') || item.service_available === false,
        }"
        :style="{ '--accent': platformAccentColor(item.code) }"
      >
        <div class="platform-matrix-card-head">
          <div class="platform-matrix-card-title">
            <PlatformBadge :code="item.code" size="md" icon-only />
            <div>
              <b>{{ item.name }}</b>
              <small>{{ item.channel_label }}</small>
            </div>
          </div>
          <div class="platform-matrix-card-tags">
            <span class="platform-matrix-channel-tag" :class="{ 'is-mobile': item.channel === 'mobile' }">
              {{ item.channel === 'mobile' ? '移动' : '网页' }}
            </span>
            <span
              v-for="label in (item.labels || [])"
              :key="label"
              class="platform-matrix-shelf-tag"
              :class="{ 'is-delisted': label === '已下架', 'is-unavailable': label === '无服务' }"
            >
              {{ label }}
            </span>
          </div>
        </div>

        <div class="platform-matrix-metrics">
          <div>
            <span>今日探测</span>
            <strong>{{ item.probe_total }}</strong>
          </div>
          <div>
            <span>成功</span>
            <strong class="is-success">{{ item.probe_success }}</strong>
          </div>
          <div>
            <span>失败</span>
            <strong :class="{ 'is-failed': item.probe_failed > 0 }">{{ item.probe_failed }}</strong>
          </div>
        </div>
      </article>
    </div>
    <div v-else class="platform-matrix-empty">暂无平台数据。</div>
  </section>
</template>

<style scoped>
.platform-matrix-refresh-btn :deep(svg.is-spinning) {
  animation: platform-matrix-spin 0.8s linear infinite;
}

@keyframes platform-matrix-spin {
  to { transform: rotate(360deg); }
}
</style>
