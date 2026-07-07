<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  AlertTriangle,
  Database,
  Download,
  Globe,
  Info,
  RefreshCw,
} from '@lucide/vue'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import { useSourceAnalysis, type SourceDatePreset } from '../composables/useSourceAnalysis'
import { useAuthStore } from '../../../stores/auth'
import '../../../styles/source-analysis.css'

const auth = useAuthStore()
const pageMenuName = computed(() => (
  auth.allowedMenus.find(menu => ['customer.sources', 'platform.sources'].includes(menu.menu_code))?.menu_name || '信源'
))

const structureChartRef = ref<HTMLDivElement | null>(null)
const trendChartRef = ref<HTMLDivElement | null>(null)

const {
  brandAsset,
  isCustomerView,
  customerPeriodLabel,
  trendPeriodLabel,
  loading,
  datePreset,
  platformFilter,
  categoryFilter,
  keywordFilter,
  platformTabs,
  filteredSources,
  topSources,
  sourceTotalCount,
  uniqueSourceCount,
  platformWithSourcesCount,
  categoryStats,
  topCategory,
  officialRate,
  sourceTrendRows,
  structureChartHeight,
  hasStructurePanel,
  insight,
  loadSummary,
  resetFilters,
  exportCsv,
  sourceCategoryLabels,
  domainFromUrl,
} = useSourceAnalysis({ structureChartRef, trendChartRef })

const datePresets: Array<{ value: SourceDatePreset; label: string }> = [
  { value: '7', label: '近 7 天' },
  { value: '30', label: '近 30 天' },
  { value: 'all', label: '全部' },
]

const categoryOptions = [
  { value: 'all', label: '全部类型' },
  ...Object.entries(sourceCategoryLabels).map(([value, label]) => ({ value, label })),
]
</script>

<template>
  <section class="source-page">
    <header class="source-sticky-bar">
      <div class="source-sticky-inner">
        <div class="source-sticky-row">
          <div v-if="isCustomerView" class="source-customer-period">{{ customerPeriodLabel }}</div>
          <div v-else class="source-date-presets">
            <button
              v-for="preset in datePresets"
              :key="preset.value"
              type="button"
              :class="{ active: datePreset === preset.value }"
              @click="datePreset = preset.value"
            >
              {{ preset.label }}
            </button>
          </div>
          <input
            v-model="keywordFilter"
            class="source-search-input"
            placeholder="搜索信源标题、域名、露出词或监测问题"
          />
          <div class="source-sticky-filters">
            <select v-model="categoryFilter">
              <option v-for="option in categoryOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </div>
          <div class="source-sticky-actions">
            <span v-if="loading" class="competitor-loading-dot">更新中…</span>
            <button type="button" class="filter-reset-btn tiny-btn" @click="resetFilters">重置</button>
            <button type="button" class="filter-reset-btn tiny-btn" :disabled="loading" @click="loadSummary()">
              <RefreshCw />
              刷新
            </button>
            <button type="button" class="primary-btn small-btn" :disabled="!filteredSources.length" @click="exportCsv">
              <Download />
              导出 CSV
            </button>
          </div>
        </div>
        <div v-if="platformTabs.length > 1" class="source-platform-chips">
          <button
            v-for="tab in platformTabs"
            :key="tab.code"
            type="button"
            class="source-platform-chip"
            :class="{ active: platformFilter === tab.code }"
            @click="platformFilter = tab.code"
          >
            <PlatformBadge v-if="tab.code !== 'all'" :code="tab.code" size="xs" icon-only class="source-platform-chip-icon" />
            <Globe v-else class="source-platform-chip-globe" />
            <span>{{ tab.name }}</span>
            <em>{{ tab.count }} 次</em>
          </button>
        </div>
      </div>
    </header>

    <article class="source-hero panel">
      <div class="source-hero-top">
        <span class="source-hero-eyebrow">{{ pageMenuName }} · AI 引用溯源</span>
        <h2>{{ brandAsset?.brand_name || '本品牌' }} · 含露出词信源</h2>
        <p class="source-hero-note">
          仅展示引用<strong>标题或链接中含品牌露出词</strong>的文章，便于追踪 AI 直接引用品牌相关内容的情况。
        </p>
      </div>
      <div v-if="loading && !filteredSources.length" class="mini-empty">信源数据加载中…</div>
      <div v-else class="source-hero-metrics">
        <div class="source-hero-metric primary-metric">
          <span>引用总次数</span>
          <b>{{ sourceTotalCount }}</b>
          <em>筛选范围内累计引用</em>
        </div>
        <div class="source-hero-metric">
          <span>独立信源数</span>
          <b>{{ uniqueSourceCount }}</b>
          <em>去重 URL 数量</em>
        </div>
        <div class="source-hero-metric">
          <span>覆盖平台</span>
          <b>{{ platformWithSourcesCount }}</b>
          <em>有引用记录的模型平台</em>
        </div>
        <div class="source-hero-metric">
          <span>主要类型</span>
          <b>{{ topCategory?.name || '—' }}</b>
          <em>官网占比 {{ officialRate }}%</em>
        </div>
      </div>
    </article>

    <div class="source-insight" :class="`is-${insight.level}`">
      <div class="source-insight-icon">
        <AlertTriangle v-if="insight.level === 'empty'" />
        <Info v-else />
      </div>
      <div>
        <strong>{{ insight.title }}</strong>
        <p>{{ insight.body }}</p>
      </div>
    </div>

    <template v-if="hasStructurePanel || filteredSources.length">
      <section class="source-analytics-grid">
        <article v-if="hasStructurePanel" class="source-panel">
          <div class="source-panel-head">
            <div>
              <h3>分平台信源结构</h3>
              <p>各已购模型引用来源的类型占比</p>
            </div>
            <Database />
          </div>
          <div
            ref="structureChartRef"
            class="echart-box source-structure-echart"
            :style="{ height: `${structureChartHeight}px` }"
          />
        </article>

        <article class="source-panel">
          <div class="source-panel-head">
            <div>
              <h3>信源类型分布</h3>
              <p>官网 / 媒体 / 问答 / 社交 / 百科</p>
            </div>
          </div>
          <div v-if="filteredSources.length" class="source-category-list">
            <div v-for="item in categoryStats" :key="item.key" class="source-category-row">
              <span>{{ item.name }}</span>
              <div class="source-category-bar">
                <i :style="{ width: `${Math.max(item.percent, item.count ? 4 : 0)}%` }" />
              </div>
              <em>{{ item.percent }}%</em>
            </div>
          </div>
          <div v-else class="mini-empty chart-empty">当前筛选下暂无含露出词信源。</div>
        </article>
      </section>

      <template v-if="filteredSources.length">
        <article class="source-panel">
          <div class="source-panel-head">
            <div>
              <h3>引用趋势</h3>
              <p>{{ isCustomerView ? '按检测日统计露出词信源引用次数' : '按检测日统计新增引用次数' }}</p>
            </div>
            <span v-if="isCustomerView" class="source-customer-period">{{ trendPeriodLabel }}</span>
          </div>
          <div
            v-if="sourceTrendRows.some(item => item.value > 0)"
            ref="trendChartRef"
            class="echart-box source-trend-echart"
          />
          <div v-else class="mini-empty chart-empty">当前筛选下暂无趋势数据。</div>
        </article>

      <section class="source-panel">
        <div class="source-panel-head">
          <div>
            <h3>高频信源 TOP 5</h3>
            <p>含露出词且被重复引用最多的来源</p>
          </div>
        </div>
        <div class="source-top-grid">
          <article
            v-for="(source, index) in topSources"
            :key="source.url"
            class="source-top-card"
            :class="{ 'is-top': index === 0 }"
          >
            <span class="source-top-rank">{{ index + 1 }}</span>
            <a :href="source.url" target="_blank" rel="noopener noreferrer" class="source-top-title-link">
              {{ source.title || domainFromUrl(source.url) }}
            </a>
            <small>{{ domainFromUrl(source.url) }}</small>
            <div class="source-top-card-foot">
              <strong>{{ source.count }}</strong>
              <span class="source-type-tag">{{ sourceCategoryLabels[source.category] }}</span>
            </div>
          </article>
        </div>
      </section>

      <article class="source-panel source-table-panel">
        <div class="source-panel-head" style="padding: 16px 16px 0">
          <div>
            <h3>信源明细</h3>
            <p>共 {{ filteredSources.length }} 条含露出词信源 · {{ sourceTotalCount }} 次引用</p>
          </div>
        </div>
        <div class="source-table-head">
          <span>#</span>
          <span>信源</span>
          <span>问题</span>
          <span>露出词</span>
          <span>次数</span>
        </div>
        <div v-for="(source, index) in filteredSources" :key="source.url" class="source-table-row">
          <span>{{ index + 1 }}</span>
          <div class="source-table-main">
            <a :href="source.url" target="_blank" rel="noopener noreferrer" class="source-table-title-link">
              {{ source.title || domainFromUrl(source.url) }}
            </a>
            <small>{{ domainFromUrl(source.url) }}</small>
          </div>
          <div class="source-table-tags">
            <i v-for="question in (source.questions || []).slice(0, 3)" :key="`${source.url}-${question}`">{{ question }}</i>
            <i v-if="(source.questions || []).length > 3" class="source-table-muted">+{{ source.questions!.length - 3 }}</i>
          </div>
          <div class="source-table-tags">
            <i v-for="term in (source.exposure_terms || []).slice(0, 3)" :key="`${source.url}-${term}`" class="is-exposure">{{ term }}</i>
          </div>
          <strong>{{ source.count }}</strong>
        </div>
      </article>
      </template>
    </template>

    <div v-else-if="!loading" class="source-empty-state">
      <Database />
      <h3>暂无含露出词的信源</h3>
      <p>仅展示标题或链接中包含品牌露出词的引用文章。请尝试切换「全部」时间范围，或等待更多监测结果同步。</p>
    </div>
  </section>
</template>
