<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { RefreshCw } from '@lucide/vue'
import {
  fetchGoodsCardSummary,
  type GoodsCardHit,
  type GoodsCardSummary,
} from '../../../services/goodsCards'
import { notifyOperationError } from '../../../utils/requestError'
import { parsePreviewTenantId } from '../customerPreview'
import { useAuthStore } from '../../../stores/auth'
import ImageZoomPreview from '../../../components/ImageZoomPreview.vue'

const PAGE_SIZE = 10
const auth = useAuthStore()
const route = useRoute()
const loading = ref(false)
const summary = ref<GoodsCardSummary | null>(null)
const previewImg = ref<string | null>(null)
const detailExpanded = ref(false)
const filterPlatform = ref('')
const filterBrandKey = ref('')
const detailPage = ref(1)
const platformMenuOpen = ref(false)
const brandMenuOpen = ref(false)
const hitPanelRef = ref<HTMLElement | null>(null)

const tenantId = computed(() => {
  const preview = parsePreviewTenantId(route)
  if (preview) return preview
  const q = Number(route.query.tenant_id)
  if (Number.isFinite(q) && q > 0) return q
  return auth.session?.identity?.tenant_id || null
})

function rowBrandKey(h: GoodsCardHit): string {
  if (h.brand_hit) return 'own'
  const comp = h.comp_hits?.[0]
  if (!comp) return 'unknown'
  const base = comp.split('(')[0]?.trim() || comp
  return `comp:${base}`
}

const filteredHitsAll = computed(() => {
  let rows = summary.value?.hits || []
  if (filterPlatform.value) rows = rows.filter(h => h.platform === filterPlatform.value)
  if (filterBrandKey.value) rows = rows.filter(h => rowBrandKey(h) === filterBrandKey.value)
  return rows
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredHitsAll.value.length / PAGE_SIZE)))

const paginatedHits = computed(() => {
  const start = (detailPage.value - 1) * PAGE_SIZE
  return filteredHitsAll.value.slice(start, start + PAGE_SIZE)
})

const platformFilterOptions = computed(() => {
  const map = new Map<string, string>()
  for (const h of summary.value?.hits || []) {
    if (h.platform) map.set(h.platform, h.platform_cn || h.platform)
  }
  return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1], 'zh-CN'))
})

const brandFilterOptions = computed(() => {
  const opts: Array<{ value: string; label: string }> = [
    { value: 'own', label: '本品' },
    { value: 'unknown', label: '未识别' },
  ]
  for (const row of summary.value?.brand_competitor_rows.filter(r => !r.is_brand) || []) {
    opts.push({ value: `comp:${row.name}`, label: `竞品·${row.name}` })
  }
  return opts
})

const filterActiveLabel = computed(() => {
  if (!filterBrandKey.value) return ''
  if (filterBrandKey.value === 'own') return '本品'
  if (filterBrandKey.value === 'unknown') return '未识别'
  if (filterBrandKey.value.startsWith('comp:')) return `竞品·${filterBrandKey.value.slice(5)}`
  return filterBrandKey.value
})

const pageNumbers = computed(() => {
  const total = totalPages.value
  const current = detailPage.value
  const nums: number[] = []
  for (let p = Math.max(1, current - 2); p <= Math.min(total, current + 2); p += 1) nums.push(p)
  return nums
})

function fmtRate(v: number | null | undefined) {
  return v == null ? '—' : `${v}%`
}

function gapClass(v: number | null | undefined) {
  if (v == null) return ''
  if (v < 0) return 'is-pos'
  if (v > 0) return 'value-warn'
  return ''
}

function emptyText(s: GoodsCardSummary) {
  if (s.empty_reason === 'no_mobile_platform') return '当前日常监测未含手机端，暂无商品卡样本'
  if (s.empty_reason === 'no_completed_samples') return '近窗内暂无已完成的日常监测样本'
  if (s.empty_reason === 'no_goods') return '近窗内已完成监测，但尚未出现商品卡'
  return ''
}

function hitTermLabel(h: GoodsCardHit) {
  const terms: string[] = []
  if (h.brand_term) terms.push(h.brand_term)
  for (const c of h.comp_hits || []) terms.push(c)
  return terms.length ? terms.join('、') : '—'
}

function matchTags(h: GoodsCardHit) {
  if (h.brand_hit) return [{ text: '本品', kind: 'own' as const }]
  if (h.comp_hits?.length) {
    return h.comp_hits.slice(0, 2).map(text => ({ text, kind: 'comp' as const }))
  }
  return [{ text: '未识别', kind: 'unk' as const }]
}

async function load() {
  loading.value = true
  try {
    summary.value = await fetchGoodsCardSummary({
      tenant_id: tenantId.value,
      days: 7,
    })
    resetDetailFilters()
    detailExpanded.value = false
  } catch (error: unknown) {
    summary.value = null
    notifyOperationError(error, '商品卡分析加载失败')
  } finally {
    loading.value = false
  }
}

function resetDetailFilters() {
  filterPlatform.value = ''
  filterBrandKey.value = ''
  detailPage.value = 1
  platformMenuOpen.value = false
  brandMenuOpen.value = false
}

async function drillToBrand(name: string, isBrand: boolean, hitCount: number) {
  if (hitCount <= 0) return
  filterBrandKey.value = isBrand ? 'own' : `comp:${name}`
  filterPlatform.value = ''
  detailPage.value = 1
  detailExpanded.value = true
  await nextTick()
  hitPanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  hitPanelRef.value?.classList.add('is-drill-target')
  window.setTimeout(() => hitPanelRef.value?.classList.remove('is-drill-target'), 1200)
}

function toggleDetailSection() {
  detailExpanded.value = !detailExpanded.value
}

function setPlatformFilter(value: string) {
  filterPlatform.value = value
  detailPage.value = 1
  platformMenuOpen.value = false
}

function setBrandFilter(value: string) {
  filterBrandKey.value = value
  detailPage.value = 1
  brandMenuOpen.value = false
}

function onDocumentClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (!target?.closest('.th-filter-wrap')) {
    platformMenuOpen.value = false
    brandMenuOpen.value = false
  }
}

async function copyAppLink(url: string) {
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
  } catch {
    /* ponytail: 复制失败时浏览器会拦，不额外弹 tip */
  }
}

watch(filteredHitsAll, rows => {
  if (detailPage.value > Math.max(1, Math.ceil(rows.length / PAGE_SIZE))) {
    detailPage.value = 1
  }
})

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  void load()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
})

watch(tenantId, () => {
  void load()
})
</script>

<template>
  <section class="goods-cards-page">
    <div v-if="loading && !summary" class="mini-empty">加载中…</div>
    <template v-else-if="summary">
      <div class="page-meta-row">
        <div class="sticky-bar">
          <span class="period-chip">近 7 天</span>
          <span class="filter-chip">{{ summary.brand_label }}</span>
          <span v-if="summary.start_date" class="filter-chip muted-chip">
            {{ summary.start_date }} ~ {{ summary.end_date }}
          </span>
        </div>
        <button class="plain-btn refresh-btn" type="button" :disabled="loading" @click="load">
          <RefreshCw :size="16" />
          刷新
        </button>
      </div>

      <div v-if="emptyText(summary)" class="mini-empty">{{ emptyText(summary) }}</div>

      <template v-if="!emptyText(summary)">
        <section v-if="summary.diagnosis" class="diag-layer">
          <div class="diag-conclusion">
            <p class="diag-headline">{{ summary.diagnosis.headline }}</p>
          </div>
          <div class="diag-split">
            <div class="diag-card diag-opp">
              <div class="diag-card-title">机会</div>
              <p>{{ summary.diagnosis.opportunity }}</p>
            </div>
            <div
              class="diag-card"
              :class="summary.diagnosis.risk_title === '风险' ? 'diag-risk' : 'diag-watch'"
            >
              <div class="diag-card-title">{{ summary.diagnosis.risk_title }}</div>
              <p>{{ summary.diagnosis.risk_text }}</p>
            </div>
            <div class="diag-card diag-priority">
              <div class="diag-card-title">优先平台</div>
              <p>{{ summary.diagnosis.priority_text }}</p>
            </div>
          </div>
          <div class="panel diag-actions">
            <div class="panel-head"><h2>可执行建议</h2></div>
            <ul class="diag-action-list">
              <li v-for="(a, i) in summary.diagnosis.actions" :key="i">{{ a }}</li>
            </ul>
          </div>
        </section>

        <details class="stats-note">
          <summary>统计口径说明</summary>
          <div class="stats-note-body">
            <p>{{ summary.stats_note }}</p>
            <p v-if="summary.denominator_platform_labels.length">
              分母平台：{{ summary.denominator_platform_labels.join('、') }} · 样本 {{ summary.sample_total }} 条
            </p>
          </div>
        </details>

        <div class="status-grid">
          <div class="status-card">
            <div class="label">出卡率</div>
            <div class="value">{{ fmtRate(summary.kpi.out_rate) }}</div>
            <div class="note">{{ summary.kpi.out_note }}</div>
          </div>
          <div class="status-card">
            <div class="label">本品牌出卡率</div>
            <div class="value">{{ fmtRate(summary.kpi.brand_rate) }}</div>
            <div class="note">{{ summary.kpi.brand_note }}</div>
          </div>
          <div class="status-card">
            <div class="label">相对最强竞品差距</div>
            <div class="value" :class="gapClass(summary.kpi.gap_vs_top_comp)">
              {{ summary.kpi.gap_vs_top_comp == null ? '—' : `${summary.kpi.gap_vs_top_comp > 0 ? '+' : ''}${summary.kpi.gap_vs_top_comp}%` }}
            </div>
            <div class="note">{{ summary.kpi.gap_note }}</div>
          </div>
          <div class="status-card">
            <div class="label">未识别商品占比</div>
            <div class="value">{{ fmtRate(summary.kpi.unknown_rate) }}</div>
            <div class="note">{{ summary.kpi.unknown_note }}</div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <h2>本品 / 竞品出卡</h2>
              <p>点「查看命中明细」跳转下方表格并自动筛品牌；红色表示竞品出卡率高于本品</p>
            </div>
          </div>
          <table class="data-table">
            <thead>
              <tr><th>品牌</th><th>命中条数</th><th>出卡率</th><th>命中明细</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in summary.brand_competitor_rows" :key="row.name">
                <td>{{ row.name }}{{ row.is_brand ? '（本品）' : '' }}</td>
                <td>{{ row.hit }}</td>
                <td
                  :class="!row.is_brand && summary.kpi.brand_rate != null && row.rate != null && row.rate > summary.kpi.brand_rate ? 'rate-bad' : ''"
                >
                  {{ fmtRate(row.rate) }}
                </td>
                <td>
                  <button
                    v-if="row.hit > 0"
                    type="button"
                    class="drill-link-btn"
                    @click="drillToBrand(row.name, row.is_brand, row.hit)"
                  >
                    查看命中明细（共 {{ row.hit }} 条）
                  </button>
                  <span v-else class="muted">无</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="panel">
          <div class="panel-head"><div><h2>问法维度</h2><p>哪些问法更容易出卡 / 更容易丢本品牌货架</p></div></div>
          <table class="data-table">
            <thead>
              <tr><th>问法</th><th>样本</th><th>出卡</th><th>出卡率</th><th>本品牌出卡</th><th>本品牌率</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in summary.prompt_rows" :key="row.prompt">
                <td>{{ row.prompt }}</td>
                <td>{{ row.total }}</td>
                <td>{{ row.goods }}</td>
                <td>{{ fmtRate(row.out_rate) }}</td>
                <td>{{ row.brand }}</td>
                <td>{{ fmtRate(row.brand_rate) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="panel">
          <div class="panel-head"><div><h2>分平台</h2><p>仅展示进入分母集的平台</p></div></div>
          <table class="data-table">
            <thead>
              <tr><th>平台</th><th>样本</th><th>出卡</th><th>出卡率</th><th>本品牌出卡</th><th>本品牌率</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in summary.platform_rows" :key="row.platform">
                <td><span class="plat-pill">{{ row.platform_cn }}</span></td>
                <td>{{ row.total }}</td>
                <td>{{ row.goods }}</td>
                <td>{{ fmtRate(row.out_rate) }}</td>
                <td>{{ row.brand }}</td>
                <td>{{ fmtRate(row.brand_rate) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div
          id="goods-card-hits"
          ref="hitPanelRef"
          class="panel hit-detail-panel"
        >
          <button
            type="button"
            class="section-toggle"
            :aria-expanded="detailExpanded"
            @click="toggleDetailSection"
          >
            <div>
              <h2>命中明细</h2>
              <p>服务端分页：每页 {{ PAGE_SIZE }} 条；筛选后从第 1 页开始（共 {{ summary.hits.length }} 条命中记录）</p>
            </div>
            <span class="toggle-icon">{{ detailExpanded ? '收起明细' : '展开明细' }}</span>
          </button>

          <div v-show="detailExpanded" class="section-body">
            <div class="detail-toolbar">
              <div class="filter-count">
                显示 {{ filteredHitsAll.length }} / {{ summary.hits.length }}
              </div>
              <div v-if="filterActiveLabel" class="filter-active">{{ filterActiveLabel }}</div>
              <button type="button" class="filter-reset" @click="resetDetailFilters">重置筛选</button>
            </div>

            <div class="table-wrap">
              <table class="detail-table">
                <thead>
                  <tr>
                    <th>
                      <span class="th-filter">
                        平台
                        <span class="th-filter-wrap">
                          <button
                            type="button"
                            class="th-filter-btn"
                            :class="{ 'is-open': platformMenuOpen, 'is-active': !!filterPlatform }"
                            title="筛选平台"
                            @click.stop="platformMenuOpen = !platformMenuOpen; brandMenuOpen = false"
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
                            </svg>
                          </button>
                          <div v-show="platformMenuOpen" class="th-filter-menu">
                            <button
                              type="button"
                              :class="{ 'is-selected': !filterPlatform }"
                              @click="setPlatformFilter('')"
                            >全部</button>
                            <button
                              v-for="[code, label] in platformFilterOptions"
                              :key="code"
                              type="button"
                              :class="{ 'is-selected': filterPlatform === code }"
                              @click="setPlatformFilter(code)"
                            >{{ label }}</button>
                          </div>
                        </span>
                      </span>
                    </th>
                    <th>问法</th>
                    <th>商品</th>
                    <th>
                      <span class="th-filter">
                        匹配
                        <span class="th-filter-wrap">
                          <button
                            type="button"
                            class="th-filter-btn"
                            :class="{ 'is-open': brandMenuOpen, 'is-active': !!filterBrandKey }"
                            title="筛选品牌"
                            @click.stop="brandMenuOpen = !brandMenuOpen; platformMenuOpen = false"
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
                            </svg>
                          </button>
                          <div v-show="brandMenuOpen" class="th-filter-menu">
                            <button
                              type="button"
                              :class="{ 'is-selected': !filterBrandKey }"
                              @click="setBrandFilter('')"
                            >全部</button>
                            <button
                              v-for="opt in brandFilterOptions"
                              :key="opt.value"
                              type="button"
                              :class="{ 'is-selected': filterBrandKey === opt.value }"
                              @click="setBrandFilter(opt.value)"
                            >{{ opt.label }}</button>
                          </div>
                        </span>
                      </span>
                    </th>
                    <th>命中词</th>
                    <th>答图</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(h, idx) in paginatedHits"
                    :key="`${h.subtask_id}-${idx}`"
                    class="drill-row"
                    :class="{ 'hit-row--own': h.brand_hit }"
                  >
                    <td class="col-platform"><span class="plat-pill">{{ h.platform_cn }}</span></td>
                    <td class="col-prompt"><span>{{ h.prompt }}</span></td>
                    <td class="col-goods">
                      <div class="goods-cell">
                        <button
                          v-if="h.thumbnail"
                          type="button"
                          class="goods-thumb-btn"
                          title="点击放大商品图"
                          @click="previewImg = h.thumbnail"
                        >
                          <img class="goods-thumb" :src="h.thumbnail" alt="" loading="lazy" />
                        </button>
                        <span v-else class="goods-thumb goods-thumb--empty">图</span>
                        <div class="goods-meta">
                          <div class="goods-title">{{ h.title }}</div>
                          <div v-if="h.price || h.mall" class="goods-sub">
                            <span v-if="h.price">{{ h.price }}</span>
                            <span v-if="h.mall">{{ h.price ? ' · ' : '' }}{{ h.mall }}</span>
                          </div>
                          <div class="goods-link-row">
                            <a
                              v-if="h.link_kind === 'http' && h.url"
                              class="goods-link"
                              :href="h.url"
                              target="_blank"
                              rel="noopener"
                            >商品链接</a>
                            <button
                              v-else-if="h.link_kind === 'app' && h.url"
                              type="button"
                              class="goods-link goods-link--app"
                              @click="copyAppLink(h.url || '')"
                            >App 内链 · 复制</button>
                            <span v-else class="muted">无链接</span>
                          </div>
                        </div>
                      </div>
                    </td>
                    <td class="col-tags">
                      <span
                        v-for="tag in matchTags(h)"
                        :key="tag.text"
                        class="tag"
                        :class="tag.kind === 'own' ? 'tag-own' : tag.kind === 'comp' ? 'tag-comp' : 'tag-unk'"
                      >{{ tag.text }}</span>
                    </td>
                    <td class="col-term">{{ hitTermLabel(h) }}</td>
                    <td class="col-shot">
                      <button
                        v-if="h.page_screenshot"
                        type="button"
                        class="shot-thumb-btn"
                        title="点击放大答图"
                        @click="previewImg = h.page_screenshot"
                      >
                        <img class="shot-mini" :src="h.page_screenshot" alt="" loading="lazy" />
                      </button>
                      <span v-else class="muted">无</span>
                    </td>
                  </tr>
                  <tr v-if="!paginatedHits.length">
                    <td colspan="6" class="mini-empty">暂无命中明细</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-if="filteredHitsAll.length > PAGE_SIZE" class="pager">
              <div class="pager-info">第 {{ detailPage }} / {{ totalPages }} 页</div>
              <button type="button" class="pager-btn" :disabled="detailPage <= 1" @click="detailPage -= 1">上一页</button>
              <button
                v-for="p in pageNumbers"
                :key="p"
                type="button"
                class="pager-btn"
                :class="{ 'is-current': p === detailPage }"
                @click="detailPage = p"
              >{{ p }}</button>
              <button type="button" class="pager-btn" :disabled="detailPage >= totalPages" @click="detailPage += 1">下一页</button>
            </div>
          </div>
        </div>
      </template>
    </template>

    <ImageZoomPreview :src="previewImg" @close="previewImg = null" />
  </section>
</template>

<style scoped>
/* 2026-09-02 - 对齐桌面商品卡范例：诊断/KPI/表格/命中明细分页筛选 */
.goods-cards-page { display: flex; flex-direction: column; gap: 16px; }
.page-meta-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.sticky-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.period-chip {
  padding: 7px 12px; border-radius: 999px;
  background: rgba(45, 108, 223, 0.08); color: #2d6cdf;
  font-size: 13px; font-weight: 600;
}
.filter-chip {
  padding: 7px 12px; border: 1px solid #d9e8f6; border-radius: 999px;
  background: #fff; color: #58708f; font-size: 12px; font-weight: 600;
}
.muted-chip { color: #8796ab; }
.refresh-btn { flex-shrink: 0; }

.diag-layer { display: flex; flex-direction: column; gap: 14px; margin-bottom: 4px; }
.diag-conclusion {
  padding: 20px 22px; border: 1px solid #c5daf5; border-radius: 10px;
  background: linear-gradient(135deg, #eef5ff 0%, #f8fbff 55%, #fff 100%);
  box-shadow: 0 10px 28px rgba(35, 72, 118, 0.06);
}
.diag-headline { margin: 0; font-size: 17px; font-weight: 600; line-height: 1.65; color: #12325a; }
.diag-split { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.diag-card {
  padding: 16px 18px; border-radius: 8px; border: 1px solid #dce6f1;
  background: #fff; box-shadow: 0 8px 22px rgba(35, 72, 118, 0.05);
}
.diag-card p { margin: 0; font-size: 13px; line-height: 1.65; color: #4a607e; }
.diag-card-title { font-size: 13px; font-weight: 700; margin-bottom: 8px; }
.diag-opp .diag-card-title { color: #0a916d; }
.diag-risk .diag-card-title { color: #dc2626; }
.diag-watch .diag-card-title { color: #b45309; }
.diag-priority .diag-card-title { color: #2d6cdf; }
.diag-action-list { margin: 0; padding-left: 20px; color: #4a607e; font-size: 13px; line-height: 1.75; }
.diag-action-list li { margin-bottom: 6px; }

.stats-note { margin-bottom: 0; border: 1px solid #dce6f1; border-radius: 8px; padding: 10px 12px; background: #fff; }
.stats-note summary { cursor: pointer; color: #58708f; font-size: 12px; font-weight: 600; }
.stats-note-body { margin-top: 8px; color: #657895; font-size: 12px; line-height: 1.7; }
.stats-note-body p { margin: 0 0 6px; }

.status-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.status-card {
  position: relative; overflow: hidden; padding: 21px;
  border: 1px solid #dce6f1; border-radius: 8px; background: #fff;
  box-shadow: 0 10px 28px rgba(35, 72, 118, 0.07);
}
.status-card::after {
  content: ''; position: absolute; right: -16px; top: -20px;
  width: 72px; height: 72px; border: 18px solid #eef5fd; border-radius: 50%;
}
.status-card .label { position: relative; z-index: 1; font-size: 13px; color: #7b8ba4; font-weight: 600; }
.status-card .value {
  position: relative; z-index: 1; margin-top: 10px;
  font-size: 30px; font-weight: 700; letter-spacing: -0.02em;
}
.status-card .value.value-warn { color: #dc2626; }
.status-card .note { position: relative; z-index: 1; margin-top: 6px; font-size: 12px; color: #8796ab; }

.panel {
  padding: 22px; border: 1px solid #dce6f1; border-radius: 8px;
  background: #fff; box-shadow: 0 10px 28px rgba(35, 72, 118, 0.07);
}
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 16px; }
.panel-head h2 { margin: 0; font-size: 18px; color: #17233d; }
.panel-head p { margin: 5px 0 0; color: #7890ab; font-size: 12px; line-height: 1.6; }

.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th, .data-table td {
  text-align: left; padding: 12px 10px; border-bottom: 1px solid #e8eef6; vertical-align: top;
}
.data-table th {
  color: #7890ab; font-weight: 600; font-size: 12px;
  background: #f7fbff; border-bottom: 1px solid #dce6f1;
}
.data-table tbody tr:hover td { background: #f9fbfe; }
.data-table tbody tr:last-child td { border-bottom: none; }
.rate-bad { color: #dc2626; font-weight: 700; }

.drill-link-btn {
  display: inline-flex; align-items: center; gap: 6px; min-height: 32px;
  padding: 0 12px; border: 1px solid #d9e8f6; border-radius: 999px;
  background: #fff; color: #2d6cdf; font-size: 12px; font-weight: 700; cursor: pointer;
}
.drill-link-btn:hover { background: #f3f8fd; border-color: #b9d2ec; }

.plat-pill {
  display: inline-flex; align-items: center; min-height: 26px; padding: 0 10px;
  border-radius: 999px; background: #eef5fd; color: #2d6cdf;
  font-size: 12px; font-weight: 700; white-space: nowrap;
}

.hit-detail-panel.is-drill-target { box-shadow: 0 0 0 3px rgba(45, 108, 223, 0.18); transition: box-shadow 0.35s ease; }
.section-toggle {
  display: flex; align-items: center; justify-content: space-between; width: 100%;
  padding: 0; border: 0; background: transparent; cursor: pointer; text-align: left;
}
.section-toggle h2 { margin: 0; font-size: 18px; color: #17233d; }
.section-toggle p { margin: 5px 0 0; color: #7890ab; font-size: 12px; }
.toggle-icon { color: #2d6cdf; font-size: 13px; font-weight: 700; white-space: nowrap; }
.section-body { margin-top: 16px; }

.detail-toolbar {
  display: flex; align-items: center; justify-content: flex-end; gap: 12px;
  flex-wrap: wrap; margin-bottom: 12px;
}
.filter-count { color: #8796ab; font-size: 12px; font-weight: 600; margin-right: auto; }
.filter-active {
  padding: 6px 10px; border-radius: 999px; background: #eef5fd;
  color: #2d6cdf; font-size: 12px; font-weight: 700;
}
.filter-reset {
  min-height: 30px; padding: 0 12px; border: 1px solid #d9e8f6; border-radius: 8px;
  background: #fff; color: #2d6cdf; font-size: 12px; font-weight: 700; cursor: pointer;
}
.filter-reset:hover { background: #f3f8fd; }

.table-wrap {
  overflow: auto; border: 1px solid #e6eef8; border-radius: 12px; background: #fff;
}
.detail-table {
  width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0;
}
.detail-table th, .detail-table td {
  text-align: left; padding: 14px 12px; border-bottom: 1px solid #eef3f9; vertical-align: middle;
}
.detail-table th {
  color: #6a7f9a; font-weight: 700; font-size: 12px; background: #f7fbff;
  position: sticky; top: 0; z-index: 1;
}
.detail-table tbody tr.drill-row:hover td { background: #f5f9ff; }
.detail-table tbody tr.drill-row:last-child td { border-bottom: none; }
.hit-row--own td { background: #f3faf7; }
.col-platform { width: 11%; }
.col-prompt { width: 14%; }
.col-goods { width: 28%; min-width: 220px; }
.col-tags { width: 10%; }
.col-term { width: 12%; color: #58708f; font-size: 12px; }
.col-shot { width: 10%; }
.col-prompt span {
  display: -webkit-box; overflow: hidden; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  line-height: 1.4; color: #4b5f78; font-size: 12px;
}

.th-filter { display: inline-flex; align-items: center; gap: 6px; user-select: none; }
.th-filter-wrap { position: relative; display: inline-flex; }
.th-filter-btn {
  display: inline-grid; place-items: center; width: 22px; height: 22px; padding: 0;
  border: 1px solid transparent; border-radius: 6px; background: transparent;
  color: #8aa0ba; cursor: pointer;
}
.th-filter-btn:hover, .th-filter-btn.is-open { color: #2d6cdf; background: #eaf3ff; border-color: #cfe1f5; }
.th-filter-btn.is-active { color: #fff; background: #2868db; border-color: #2868db; }
.th-filter-btn svg { width: 12px; height: 12px; display: block; }
.th-filter-menu {
  position: absolute; top: calc(100% + 6px); left: 0; z-index: 20;
  min-width: 168px; max-width: 240px; max-height: 260px; overflow: auto;
  padding: 6px; border: 1px solid #dce6f1; border-radius: 8px; background: #fff;
  box-shadow: 0 12px 28px rgba(35, 72, 118, 0.14);
}
.th-filter-menu button {
  display: block; width: 100%; text-align: left; min-height: 32px; padding: 0 10px;
  border: 0; border-radius: 6px; background: transparent; color: #17406a;
  font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap;
}
.th-filter-menu button:hover { background: #f3f8fd; }
.th-filter-menu button.is-selected { background: #eaf3ff; color: #2d6cdf; }

.goods-cell { display: flex; align-items: flex-start; gap: 10px; }
.goods-thumb-btn { padding: 0; border: 0; background: transparent; cursor: zoom-in; flex-shrink: 0; }
.goods-thumb-btn:hover .goods-thumb { border-color: #2d6cdf; box-shadow: 0 4px 12px rgba(45, 108, 223, 0.15); }
.goods-thumb {
  width: 52px; height: 52px; object-fit: cover; border-radius: 8px;
  border: 1px solid #e2eaf3; background: #f7fafd; display: block;
}
.goods-thumb--empty {
  display: grid; place-items: center; font-size: 11px; color: #94a3b8; font-weight: 700;
}
.goods-meta { min-width: 0; }
.goods-title { font-size: 13px; font-weight: 600; line-height: 1.45; color: #12325a; }
.goods-sub { margin-top: 3px; font-size: 11px; color: #8796ab; }
.goods-link-row { margin-top: 5px; }
.goods-link { font-size: 12px; font-weight: 700; color: #2d6cdf; background: none; border: 0; padding: 0; cursor: pointer; text-decoration: none; }
.goods-link--app { color: #2d6cdf; }
.goods-link:hover { text-decoration: underline; }

.shot-thumb-btn { padding: 0; border: 0; background: transparent; cursor: zoom-in; }
.shot-thumb-btn:hover .shot-mini { border-color: #2d6cdf; box-shadow: 0 4px 12px rgba(45, 108, 223, 0.15); }
.shot-mini {
  width: 52px; height: 52px; object-fit: cover; border-radius: 8px;
  border: 1px solid #d9e8f6; background: #f7fafd; display: block;
}

.tag {
  display: inline-flex; align-items: center; min-height: 24px; padding: 0 10px;
  border-radius: 999px; font-size: 12px; font-weight: 700; margin: 0 4px 4px 0;
}
.tag-own { background: #ecfdf5; color: #0a916d; }
.tag-comp { background: #fff1f2; color: #be123c; }
.tag-unk { background: #f1f5f9; color: #64748b; }
.muted { color: #8796ab; font-size: 12px; }

.pager {
  display: flex; align-items: center; justify-content: flex-end; gap: 8px;
  margin-top: 12px; flex-wrap: wrap;
}
.pager-info { color: #8796ab; font-size: 12px; font-weight: 600; margin-right: auto; }
.pager-btn {
  min-width: 32px; min-height: 32px; padding: 0 10px; border: 1px solid #d9e8f6;
  border-radius: 8px; background: #fff; color: #17406a; font-size: 12px; font-weight: 700; cursor: pointer;
}
.pager-btn:hover:not(:disabled) { background: #f3f8fd; color: #2d6cdf; }
.pager-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.pager-btn.is-current { color: #fff; background: #2868db; border-color: #2868db; }

@media (max-width: 1100px) {
  .diag-split, .status-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 720px) {
  .diag-split, .status-grid { grid-template-columns: 1fr; }
}
</style>
