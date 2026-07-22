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
import InclusionDetailPanel from '../components/InclusionDetailPanel.vue'
import { useSourceAnalysis, type SourceDatePreset } from '../composables/useSourceAnalysis'
import { sourceCategoryColor } from '../sourceCategory'
import { externalLink } from '../portalUtils'
import { useAuthStore } from '../../../stores/auth'
import { parsePreviewTenantId } from '../customerPreview'
import { useRoute } from 'vue-router'
import '../../../styles/source-analysis.css'

const auth = useAuthStore()
const route = useRoute()
const pageMenuName = computed(() => (
  auth.allowedMenus.find(menu => ['customer.sources', 'platform.sources'].includes(menu.menu_code))?.menu_name || '信源'
))

const structureChartRef = ref<HTMLDivElement | null>(null)
const categoryChartRef = ref<HTMLDivElement | null>(null)
const trendChartRef = ref<HTMLDivElement | null>(null)

const {
  brandAsset,
  isCustomerView,
  customerPeriodLabel,
  trendPeriodLabel,
  loading,
  datePreset,
  inclusionDateRange,
  platformFilter,
  categoryFilter,
  domainFilter,
  keywordFilter,
  rankTab,
  articlePage,
  articleTotalPages,
  rankPageSize,
  platformTabs,
  filteredSources,
  activeRankArticles,
  pagedRankArticles,
  sourceTotalCount,
  uniqueSourceCount,
  brandedWebsiteCount,
  allCitationTotalCount,
  allWebsiteCount,
  brandedCitationShare,
  platformWithSourcesCount,
  categoryStats,
  websiteShortList,
  categorySummaryLabel,
  topCategory,
  officialRate,
  sourceTrendRows,
  analyticsPairMinHeight,
  hasStructurePanel,
  hasPageContent,
  insight,
  loadSummary,
  resetFilters,
  setRankTab,
  selectWebsiteDomain,
  clearWebsiteDomain,
  exportCsv,
  sourceCategoryLabels,
  sourceCategoryLabel,
  domainFromUrl,
} = useSourceAnalysis({ structureChartRef, categoryChartRef, trendChartRef })

const inclusionTenantId = computed(() => {
  const preview = parsePreviewTenantId(route)
  if (preview != null) return preview
  return brandAsset.value?.tenant_id ?? null
})

async function openWebsiteArticles(domain: string) {
  if (!domain) return
  // 并排时再次点击同一域名 = 取消筛选，回到全部信源
  if (domainFilter.value === domain) {
    clearWebsiteDomain()
    return
  }
  selectWebsiteDomain(domain)
}

const articlePageLabel = computed(() => {
  const total = activeRankArticles.value.length
  if (!total) return '暂无文章'
  const start = (articlePage.value - 1) * rankPageSize + 1
  const end = Math.min(articlePage.value * rankPageSize, total)
  const scope = rankTab.value === 'all' ? '全部引用' : '含露出词'
  return `${scope} · 第 ${start}-${end} 条 / 共 ${total} 条`
})

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
          <div class="source-date-presets">
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
            <button type="button" class="filter-reset-btn tiny-btn" :disabled="loading" @click="loadSummary(true)">
              <RefreshCw />
              刷新
            </button>
            <button type="button" class="primary-btn small-btn" :disabled="!websiteShortList.length" @click="exportCsv">
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
        <h2>{{ brandAsset?.brand_name || '本品牌' }} · 信源分析</h2>
        <p class="source-hero-note">
          图表默认按<strong>含露出词</strong>统计；下方排行按<strong>引用网站（域名）</strong>聚合。
        </p>
      </div>
      <div v-if="loading && !hasPageContent" class="mini-empty">信源数据加载中…</div>
      <div v-else class="source-hero-metrics">
        <div class="source-hero-metric primary-metric">
          <span>品牌相关引用</span>
          <b>{{ sourceTotalCount }}</b>
          <em>{{ brandedWebsiteCount }} 个相关网站 · {{ uniqueSourceCount }} 篇文章</em>
        </div>
        <div class="source-hero-metric">
          <span>全部引用次数</span>
          <b>{{ allCitationTotalCount }}</b>
          <em>{{ allWebsiteCount }} 个引用网站</em>
        </div>
        <div class="source-hero-metric">
          <span>品牌相关占比</span>
          <b>{{ brandedCitationShare }}%</b>
          <em>含露出词 / 全部引用</em>
        </div>
        <div class="source-hero-metric">
          <span>覆盖平台</span>
          <b>{{ platformWithSourcesCount }}</b>
          <em>主要类型 {{ topCategory?.name || '—' }} · 官网 {{ officialRate }}%</em>
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

    <template v-if="hasPageContent">
      <section v-if="hasStructurePanel || filteredSources.length" class="source-analytics-grid">
        <article v-if="hasStructurePanel" class="source-panel source-panel--paired">
          <div class="source-panel-head">
            <div>
              <h3>分平台信源结构</h3>
              <p>各已购模型引用来源的类型占比（含露出词）</p>
            </div>
            <Database />
          </div>
          <div
            class="source-panel-body"
            :style="{ minHeight: `${analyticsPairMinHeight}px` }"
          >
            <div
              ref="structureChartRef"
              class="echart-box source-structure-echart"
            />
          </div>
        </article>

        <article class="source-panel source-panel--paired">
          <div class="source-panel-head">
            <div>
              <h3>信源类型分布</h3>
              <p>{{ categorySummaryLabel }} · 点击扇区可筛选类型</p>
            </div>
          </div>
          <div
            class="source-panel-body"
            :style="{ minHeight: `${analyticsPairMinHeight}px` }"
          >
            <div
              v-if="categoryStats.length"
              ref="categoryChartRef"
              class="echart-box source-category-echart"
            />
            <div v-else class="mini-empty chart-empty">当前筛选下暂无含露出词信源。</div>
          </div>
        </article>
      </section>

      <article v-if="sourceTrendRows.some(item => item.value > 0) || filteredSources.length" class="source-panel">
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

      <section class="source-website-detail-grid">
      <article class="source-panel source-table-panel source-type-panel">
        <div class="source-panel-head source-rank-head">
          <div>
            <h3>引用网站</h3>
            <p>按注册域合并；点击网站查看右侧信源 · 共 {{ websiteShortList.length }} 个</p>
          </div>
          <div class="source-rank-tabs">
            <button
              type="button"
              :class="{ active: rankTab === 'branded' }"
              @click="setRankTab('branded')"
            >
              品牌相关
            </button>
            <button
              type="button"
              :class="{ active: rankTab === 'all' }"
              @click="setRankTab('all')"
            >
              全部网站
            </button>
          </div>
        </div>
        <div v-if="!websiteShortList.length" class="mini-empty chart-empty" style="padding: 0 16px 16px">
          当前筛选下暂无网站。
        </div>
        <template v-else>
          <div class="source-table-head source-type-head">
            <span>发布方</span>
            <span>域名</span>
            <span>次数</span>
            <span>占比</span>
          </div>
          <div class="source-website-short-list">
            <button
              v-for="item in websiteShortList"
              :key="item.domain"
              type="button"
              class="source-table-row source-type-row"
              :class="{ active: domainFilter === item.domain }"
              :style="{ '--type-color': sourceCategoryColor(item.category) }"
              @click="openWebsiteArticles(item.domain)"
            >
              <div class="source-type-name">
                <i class="source-type-dot" aria-hidden="true" />
                <div class="source-type-name-text">
                  <span>{{ item.displayName }}</span>
                  <small v-if="item.subjectHint">文中主体：{{ item.subjectHint }}</small>
                </div>
              </div>
              <span class="source-domain-tag">{{ item.domain }}</span>
              <strong>{{ item.count }}</strong>
              <em class="source-type-percent">{{ item.percent }}%</em>
            </button>
          </div>
        </template>
      </article>

      <article id="source-article-section" class="source-panel source-table-panel source-article-panel">
        <div class="source-panel-head source-article-head">
          <div>
            <h3>信源明细</h3>
            <p>
              {{ articlePageLabel }}
              <template v-if="categoryFilter !== 'all'">
                · 已筛选「{{ sourceCategoryLabel(categoryFilter) }}」
              </template>
              <template v-if="domainFilter">
                · 网站「{{ domainFilter }}」
              </template>
            </p>
          </div>
          <button
            v-if="domainFilter"
            type="button"
            class="source-soft-btn"
            @click="clearWebsiteDomain"
          >
            清除网站筛选
          </button>
        </div>
        <div class="source-table-head">
          <span>#</span>
          <span>信源</span>
          <span>问题</span>
          <span>露出词</span>
          <span>次数</span>
        </div>
        <div v-if="!pagedRankArticles.length" class="mini-empty chart-empty">当前筛选下暂无文章。</div>
        <div v-else class="source-article-scroll">
          <div
            v-for="(source, index) in pagedRankArticles"
            :key="`${rankTab}-article-${source.url}`"
            class="source-table-row"
          >
            <span>{{ (articlePage - 1) * rankPageSize + index + 1 }}</span>
            <div class="source-table-main">
              <a :href="externalLink(source.url) || undefined" target="_blank" rel="noopener noreferrer" class="source-table-title-link">
                {{ source.title || domainFromUrl(source.url) }}
              </a>
              <small>
                <span class="source-domain-tag is-inline">{{ domainFromUrl(source.url) }}</span>
                · {{ sourceCategoryLabel(source.category) }}
              </small>
            </div>
            <div class="source-table-tags">
              <i v-for="question in (source.questions || []).slice(0, 3)" :key="`${source.url}-${question}`">{{ question }}</i>
              <i v-if="(source.questions || []).length > 3" class="source-table-muted">+{{ source.questions!.length - 3 }}</i>
            </div>
            <div class="source-table-tags">
              <i v-for="term in (source.exposure_terms || []).slice(0, 3)" :key="`${source.url}-${term}`" class="is-exposure">{{ term }}</i>
              <i v-if="!(source.exposure_terms || []).length" class="source-table-muted">—</i>
            </div>
            <strong>{{ source.count }}</strong>
          </div>
        </div>
        <div v-if="articleTotalPages > 1" class="source-soft-pager">
          <button type="button" class="source-soft-btn" :disabled="articlePage <= 1" @click="articlePage -= 1">
            上一页
          </button>
          <span>{{ articlePage }} / {{ articleTotalPages }}</span>
          <button type="button" class="source-soft-btn" :disabled="articlePage >= articleTotalPages" @click="articlePage += 1">
            下一页
          </button>
        </div>
      </article>
      </section>
    </template>

    <div v-else-if="!loading" class="source-empty-state">
      <Database />
      <h3>暂无信源引用</h3>
      <p>当前筛选下没有可展示的 AI 引用。请尝试放宽筛选，或等待更多监测结果同步。</p>
    </div>

    <InclusionDetailPanel
      :tenant-id="inclusionTenantId"
      :start-date="inclusionDateRange.startDate"
      :end-date="inclusionDateRange.endDate"
      :platform-filter="platformFilter"
      :keyword-filter="keywordFilter"
    />
  </section>
</template>
