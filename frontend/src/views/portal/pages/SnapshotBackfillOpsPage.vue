<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EyeOff, RefreshCw, Upload } from '@lucide/vue'
import '../../../styles/snapshot-backfill.css'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import SnapshotBackfillDialog from '../components/SnapshotBackfillDialog.vue'
import SnapshotBackfillDetailDrawer from '../components/SnapshotBackfillDetailDrawer.vue'
import {
  dismissSnapshotBackfill,
  getPendingSnapshotBackfills,
  undismissSnapshotBackfill,
  type SnapshotBackfillPendingItem,
} from '../../../services/snapshotBackfill'
import { getMonitorSubtask, type MonitorSubtask } from '../../../services/monitor'
import { getTenants, type TenantInfo } from '../../../services/management'
import {
  getBrandAsset,
  formatKeywordGroupDetailHint,
  keywordGroupDisplayName,
  keywordGroupMonitorKeywords,
  keywordGroupSelectValue,
  platformSelectionCodes,
  type BrandKeywordGroup,
} from '../../../services/brand'
import { useAuthStore } from '../../../stores/auth'
import { notifyOperationError } from '../../../utils/requestError'
import { withRetry } from '../../../composables/useRetry'
import { formatMonitorSubtaskRank } from '../portalUtils'
import { mergeSnapshotBackfillItem, snapshotBackfillBatchLabel } from '../snapshotBackfillDisplay'
import { emitMonitorRefresh } from '../../../utils/monitorRefresh'
import { platformLabelMap, supportedPlatforms } from '../portalMaps'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const backfillMenu = computed(() => auth.allowedMenus.find(menu => menu.menu_code === 'platform.snapshot_backfill'))
const canViewBackfill = computed(() => Boolean(backfillMenu.value?.can_export))
const canSubmitBackfill = computed(() => Boolean(backfillMenu.value?.can_update))

const PAGE_SIZE = 40
const FILTER_DEBOUNCE_MS = 350

const loading = ref(false)
const loadingMore = ref(false)
const items = ref<SnapshotBackfillPendingItem[]>([])
const listSummary = ref({
  total: 0,
  pending: 0,
  overwrite: 0,
  shown: 0,
  offset: 0,
  limit: PAGE_SIZE,
  has_more: false,
  scan_capped: false,
  summary_partial: false,
})
const loadMoreSentinel = ref<HTMLElement | null>(null)
let loadMoreObserver: IntersectionObserver | null = null
const tenants = ref<TenantInfo[]>([])
const backfillVisible = ref(false)
const backfillTarget = ref<MonitorSubtask | null>(null)
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailItem = ref<SnapshotBackfillPendingItem | null>(null)
const detailSubtask = ref<MonitorSubtask | null>(null)

const tenantFilter = ref<number | ''>('')
const filterDate = ref('')
const sourceFilter = ref<'' | 'tenant_monitor' | 'lead_diagnosis'>('')
const platformFilter = ref('')
const keywordGroupFilter = ref('')
const keywordFilter = ref('')
const keywordGroupOptions = ref<BrandKeywordGroup[]>([])
const tenantMonitoredPlatforms = ref<string[]>([])
const pendingOnly = ref(false)

let listRequestSeq = 0
let listAbortController: AbortController | null = null
let filterDebounceTimer: ReturnType<typeof setTimeout> | null = null
let filterBootstrapping = false

const platformFilterOptions = computed(() => {
  if (tenantFilter.value === '') return supportedPlatforms
  const codes = new Set<string>()
  for (const group of keywordGroupOptions.value) {
    for (const code of platformSelectionCodes(group.platforms)) {
      if (code) codes.add(code)
    }
  }
  if (!codes.size) {
    for (const code of tenantMonitoredPlatforms.value) {
      if (code) codes.add(code)
    }
  }
  if (!codes.size) return supportedPlatforms
  return supportedPlatforms.filter(platform => codes.has(platform.code))
})

const monitorKeywordOptions = computed(() => {
  const seen = new Set<string>()
  const options: string[] = []
  for (const group of keywordGroupOptions.value) {
    for (const keyword of keywordGroupMonitorKeywords(group)) {
      if (seen.has(keyword)) continue
      seen.add(keyword)
      options.push(keyword)
    }
  }
  return options.sort((left, right) => left.localeCompare(right, 'zh-CN'))
})

const pendingCount = computed(() => listSummary.value.pending)
const overwriteCount = computed(() => listSummary.value.overwrite)
const totalCount = computed(() => listSummary.value.total)
const shownCount = computed(() => items.value.length)
const hasMore = computed(() => listSummary.value.has_more && items.value.length < listSummary.value.total)
const statsTruncated = computed(() => items.value.length < listSummary.value.total)

const hasActiveFilters = computed(() => Boolean(
  tenantFilter.value !== ''
  || filterDate.value
  || sourceFilter.value
  || platformFilter.value
  || keywordGroupFilter.value
  || keywordFilter.value.trim()
  || pendingOnly.value,
))

function sourceLabel(item: SnapshotBackfillPendingItem) {
  if (item.source === 'lead_diagnosis') return '售前诊断'
  return 'GEO 监测'
}

function scopeLabel(item: SnapshotBackfillPendingItem) {
  return item.brand_name || item.tenant_name || item.monitor_keywords || '未命名任务'
}

function actionLabel(item: SnapshotBackfillPendingItem) {
  if (item.needs_backfill) return '快照补录'
  if (item.has_answer) return '覆盖更正'
  return '补录'
}

function rankMetricClass(item: SnapshotBackfillPendingItem) {
  const rank = formatMonitorSubtaskRank(item)
  return rank !== '-' && rank !== '—' && rank !== '未提及' ? 'is-rank' : ''
}

function statusLabel(item: SnapshotBackfillPendingItem) {
  if (item.needs_backfill) return '待补录'
  if (item.has_answer) return '已有结果'
  return item.status || '—'
}

function isTenantInService(tenant: TenantInfo) {
  // 与后端 tenant_service_is_operational 对齐：服务中 = 启用且在合同期内、非人工停服
  if (!tenant.status) return false
  if (tenant.stop_reason === 'manual' || tenant.stop_reason === 'canceled') return false
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  if (tenant.service_start_date) {
    const startDate = new Date(`${tenant.service_start_date} 00:00:00`)
    if (startDate.getTime() > today.getTime()) return false
  }
  if (tenant.service_end_date) {
    const endDate = new Date(`${tenant.service_end_date} 23:59:59`)
    if (endDate.getTime() < today.getTime()) return false
  }
  return true
}

async function loadTenants() {
  try {
    const rows = await withRetry(() => getTenants())
    tenants.value = rows.filter(isTenantInService)
  } catch {
    tenants.value = []
  }
  if (
    tenantFilter.value !== ''
    && !tenants.value.some(tenant => tenant.id === tenantFilter.value)
  ) {
    tenantFilter.value = tenants.value[0]?.id ?? ''
  }
}

const keywordGroupSummary = computed(() => {
  if (!keywordGroupFilter.value) return ''
  const index = keywordGroupOptions.value.findIndex(
    (group, groupIndex) => keywordGroupSelectValue(group, groupIndex) === keywordGroupFilter.value,
  )
  if (index >= 0) return keywordGroupDisplayName(keywordGroupOptions.value[index], index)
  return keywordGroupFilter.value
})

async function loadTenantKeywordGroups() {
  keywordGroupFilter.value = ''
  keywordFilter.value = ''
  tenantMonitoredPlatforms.value = []
  if (tenantFilter.value === '') {
    keywordGroupOptions.value = []
    return
  }
  try {
    const asset = await getBrandAsset(Number(tenantFilter.value))
    tenantMonitoredPlatforms.value = [...(asset.asset?.monitored_platforms || [])]
    keywordGroupOptions.value = (asset.asset?.keyword_groups || []).filter(
      (group: BrandKeywordGroup) => group.status && (group.monitor_keyword || (group.monitor_keywords || []).length),
    )
  } catch {
    keywordGroupOptions.value = []
    tenantMonitoredPlatforms.value = []
  }
}

function buildListQuery(offset = 0, includeSummary = false) {
  return {
    limit: PAGE_SIZE,
    offset,
    pending_only: pendingOnly.value,
    tenant_id: tenantFilter.value === '' ? null : Number(tenantFilter.value),
    date: filterDate.value || undefined,
    source: sourceFilter.value || undefined,
    platform: platformFilter.value || undefined,
    keyword: keywordFilter.value.trim() || undefined,
    keyword_group: keywordGroupFilter.value || undefined,
    include_summary: includeSummary,
  }
}

async function fetchPage(offset: number, append: boolean, includeSummary = false) {
  listAbortController?.abort()
  const controller = new AbortController()
  listAbortController = controller
  const seq = ++listRequestSeq
  const result = await getPendingSnapshotBackfills(buildListQuery(offset, includeSummary), { signal: controller.signal })
  if (seq !== listRequestSeq) return
  if (append) {
    const existing = new Set(items.value.map(item => item.subtask_id))
    const merged = [...items.value]
    for (const item of result.items) {
      if (!existing.has(item.subtask_id)) merged.push(item)
    }
    items.value = merged
  } else {
    items.value = result.items
  }
  listSummary.value = {
    ...result.summary,
    scan_capped: Boolean(result.summary.scan_capped),
  }
}

async function refreshSummaryInBackground() {
  // 全企业汇总极慢且易触发截断提示；仅在已选企业时后台补全统计
  if (tenantFilter.value === '') return
  const seq = listRequestSeq
  try {
    const result = await getPendingSnapshotBackfills(buildListQuery(0, true))
    if (seq !== listRequestSeq) return
    listSummary.value = {
      ...listSummary.value,
      total: result.summary.total,
      pending: result.summary.pending,
      overwrite: result.summary.overwrite,
      scan_capped: Boolean(result.summary.scan_capped),
      summary_partial: false,
    }
  } catch {
    // 汇总失败不挡列表
  }
}

async function loadItems() {
  loading.value = true
  try {
    await fetchPage(0, false, false)
    void refreshSummaryInBackground()
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    if ((error as { code?: string })?.code === 'ERR_CANCELED') return
    notifyOperationError(error, '加载补录列表失败')
  } finally {
    loading.value = false
    await nextTick()
    setupLoadMoreObserver()
  }
}

function scheduleLoadItems() {
  if (!canViewBackfill.value) return
  if (filterDebounceTimer) clearTimeout(filterDebounceTimer)
  filterDebounceTimer = setTimeout(() => {
    filterDebounceTimer = null
    void loadItems()
  }, FILTER_DEBOUNCE_MS)
}

async function loadMore() {
  if (loading.value || loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  try {
    await fetchPage(items.value.length, true)
  } catch (error: unknown) {
    notifyOperationError(error, '加载更多失败')
  } finally {
    loadingMore.value = false
    await nextTick()
    setupLoadMoreObserver()
  }
}

function setupLoadMoreObserver() {
  loadMoreObserver?.disconnect()
  if (!loadMoreSentinel.value) return
  loadMoreObserver = new IntersectionObserver(
    (entries) => {
      if (entries.some(entry => entry.isIntersecting)) void loadMore()
    },
    { root: null, rootMargin: '240px 0px' },
  )
  loadMoreObserver.observe(loadMoreSentinel.value)
}

function detectTimeLabel(item: SnapshotBackfillPendingItem) {
  return snapshotBackfillBatchLabel(item)
}

async function loadSubtask(subtaskId: string) {
  return getMonitorSubtask(subtaskId, { include_ops: true })
}

async function openDetail(item: SnapshotBackfillPendingItem) {
  detailItem.value = item
  detailVisible.value = true
  detailLoading.value = true
  detailSubtask.value = null
  try {
    detailSubtask.value = await loadSubtask(item.subtask_id)
    detailItem.value = mergeSnapshotBackfillItem(item, detailSubtask.value)
  } catch (error: unknown) {
    notifyOperationError(error, '加载快照详情失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

async function openDetailById(subtaskId: string, item: SnapshotBackfillPendingItem | null = null) {
  if (item) {
    await openDetail(item)
    return
  }
  detailItem.value = {
    subtask_id: subtaskId,
    task_id: '',
    tenant_id: null,
    tenant_name: null,
    platform: '',
    prompt: '',
    error_message: null,
    source: 'tenant_monitor',
    monitor_keywords: null,
    task_status: null,
    updated_at: null,
  }
  detailVisible.value = true
  detailLoading.value = true
  detailSubtask.value = null
  try {
    detailSubtask.value = await loadSubtask(subtaskId)
    detailItem.value = mergeSnapshotBackfillItem(detailItem.value, detailSubtask.value)
  } catch (error: unknown) {
    notifyOperationError(error, '未找到该子任务')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

function openBackfillFromDetail() {
  if (!canSubmitBackfill.value || !detailSubtask.value) return
  backfillTarget.value = detailSubtask.value
  backfillVisible.value = true
}

async function openBackfill(item: SnapshotBackfillPendingItem) {
  if (!canSubmitBackfill.value) return
  try {
    backfillTarget.value = await loadSubtask(item.subtask_id)
    backfillVisible.value = true
  } catch (error: unknown) {
    notifyOperationError(error, '加载子任务失败')
  }
}

function isFailurePending(item: SnapshotBackfillPendingItem) {
  return Boolean(item.needs_backfill) && !item.has_answer
}

async function dismissItem(item: SnapshotBackfillPendingItem) {
  if (!canSubmitBackfill.value || !item.needs_backfill) return
  try {
    if (isFailurePending(item)) {
      await ElMessageBox.confirm(
        '当前无有效回答，忽略后将不再提醒补录，客户侧仍按未抓取/失败统计（不会补出排名）。确认忽略？',
        '忽略待补录',
        { type: 'warning', confirmButtonText: '确认忽略', cancelButtonText: '取消' },
      )
    }
    await dismissSnapshotBackfill(item.subtask_id)
    items.value = items.value.filter(row => row.subtask_id !== item.subtask_id)
    if (listSummary.value.pending > 0) listSummary.value.pending -= 1
    if (listSummary.value.total > 0) listSummary.value.total -= 1
    if (detailItem.value?.subtask_id === item.subtask_id) {
      detailVisible.value = false
      detailItem.value = null
      detailSubtask.value = null
    }
    ElMessage.success('已忽略，不再提醒')
    emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })
  } catch (error: unknown) {
    if (error === 'cancel') return
    notifyOperationError(error, '忽略失败')
  }
}

async function undismissFromDetail() {
  const subtaskId = detailItem.value?.subtask_id || detailSubtask.value?.subtask_id
  if (!canSubmitBackfill.value || !subtaskId) return
  try {
    const result = await undismissSnapshotBackfill(subtaskId)
    ElMessage.success(result.item.needs_backfill ? '已取消忽略，已重新纳入待补录' : '已取消忽略')
    await loadItems()
    emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })
    await openDetailById(subtaskId, result.item)
  } catch (error: unknown) {
    notifyOperationError(error, '取消忽略失败')
  }
}

function backfillItemFromSubtask(subtask: MonitorSubtask): SnapshotBackfillPendingItem {
  return {
    subtask_id: subtask.subtask_id,
    task_id: subtask.task_id || '',
    tenant_id: subtask.tenant_id ?? null,
    tenant_name: subtask.tenant_name ?? null,
    platform: subtask.platform,
    prompt: subtask.prompt,
    error_message: subtask.error_message ?? null,
    source: (subtask.source as SnapshotBackfillPendingItem['source']) || 'tenant_monitor',
    monitor_keywords: subtask.monitor_keywords ?? null,
    task_status: subtask.status ?? null,
    updated_at: subtask.updated_at ?? null,
    mention_position: subtask.mention_position ?? null,
    has_answer: Boolean(subtask.answer_content),
    needs_backfill: subtask.needs_backfill ?? false,
    backfill_dismissed: subtask.backfill_dismissed ?? false,
    status: subtask.status ?? null,
  }
}

async function handleSuccess(updatedSubtask?: MonitorSubtask) {
  const activeId = updatedSubtask?.subtask_id || detailItem.value?.subtask_id

  await loadItems()
  emitMonitorRefresh({ tenantId: tenantFilter.value === '' ? null : Number(tenantFilter.value) })

  if (detailVisible.value && activeId) {
    if (updatedSubtask?.subtask_id === activeId) {
      detailSubtask.value = updatedSubtask
      const baseItem = detailItem.value
        || items.value.find(row => row.subtask_id === activeId)
        || backfillItemFromSubtask(updatedSubtask)
      detailItem.value = mergeSnapshotBackfillItem(baseItem, updatedSubtask)
    } else {
      const refreshed = items.value.find(row => row.subtask_id === activeId)
      if (refreshed) {
        await openDetail(refreshed)
      } else {
        await openDetailById(activeId, detailItem.value)
      }
    }
  }

  ElMessage.success('快照补录已保存，列表与详情已刷新')
  clearDeepLink()
}

function clearDeepLink() {
  const nextQuery = { ...route.query }
  delete nextQuery.subtask_id
  delete nextQuery.backfill
  void router.replace({ query: nextQuery })
}

function resetFilters() {
  tenantFilter.value = ''
  filterDate.value = ''
  sourceFilter.value = ''
  platformFilter.value = ''
  keywordGroupFilter.value = ''
  keywordFilter.value = ''
  keywordGroupOptions.value = []
  tenantMonitoredPlatforms.value = []
  pendingOnly.value = false
  void loadItems()
}

async function openFromQuery() {
  const subtaskId = String(route.query.subtask_id || '').trim()
  if (!subtaskId) return
  const wantBackfill = String(route.query.backfill || '') === '1'
  const item = items.value.find(row => row.subtask_id === subtaskId)
  if (item) {
    await openDetail(item)
  } else {
    await openDetailById(subtaskId)
  }
  if (wantBackfill && canSubmitBackfill.value && detailSubtask.value) {
    openBackfillFromDetail()
  }
}

onMounted(async () => {
  if (!canViewBackfill.value) {
    await loadTenants()
    return
  }
  await loadTenants()
  const hasDeepLink = String(route.query.backfill || '') === '1' || Boolean(route.query.subtask_id)
  // 进页默认落到具体企业，避免 all_tenants 全库扫描（数秒～十余秒）
  if (!hasDeepLink && tenantFilter.value === '' && tenants.value.length) {
    filterBootstrapping = true
    tenantFilter.value = tenants.value[0].id
    filterBootstrapping = false
  }
  await loadItems()
  setupLoadMoreObserver()
  if (hasDeepLink) {
    await openFromQuery()
  }
})

onUnmounted(() => {
  loadMoreObserver?.disconnect()
  loadMoreObserver = null
  if (filterDebounceTimer) clearTimeout(filterDebounceTimer)
  listAbortController?.abort()
})

watch(loadMoreSentinel, () => {
  setupLoadMoreObserver()
})

watch(hasMore, (value) => {
  if (value) setupLoadMoreObserver()
})

watch(
  () => route.query.subtask_id,
  async () => {
    if (route.query.subtask_id) await openFromQuery()
  },
)

watch(tenantFilter, () => {
  void loadTenantKeywordGroups()
})

watch(platformFilterOptions, (options) => {
  if (!platformFilter.value) return
  if (!options.some(platform => platform.code === platformFilter.value)) {
    platformFilter.value = ''
  }
})

watch([tenantFilter, filterDate, sourceFilter, platformFilter, keywordGroupFilter, keywordFilter, pendingOnly], () => {
  if (filterBootstrapping) return
  scheduleLoadItems()
})
</script>

<template>
  <section v-if="!canViewBackfill" class="snapshot-backfill-page snapshot-backfill-denied">
    <div class="mini-empty">
      <p>当前身份无「快照补录」查看权限（需岗位授予 can_export）。</p>
      <p>如需处理失败抓取，请联系管理员在岗位权限中开启快照补录查看与补录操作。</p>
    </div>
  </section>
  <section v-else class="snapshot-backfill-page">
    <Teleport to="#portal-page-head-extra" defer>
      <div class="snapshot-backfill-stats snapshot-backfill-stats--head">
        <article class="snapshot-backfill-stat">
          <strong>{{ totalCount }}</strong>
          <span>{{ statsTruncated ? `已加载 ${shownCount} / ${totalCount}` : '符合筛选' }}</span>
        </article>
        <article v-if="pendingCount" class="snapshot-backfill-stat is-warn">
          <strong>{{ pendingCount }}</strong>
          <span>待补录</span>
        </article>
        <article v-if="overwriteCount" class="snapshot-backfill-stat is-ok">
          <strong>{{ overwriteCount }}</strong>
          <span>可覆盖</span>
        </article>
      </div>
    </Teleport>

    <div class="snapshot-backfill-toolbar">
      <div class="snapshot-backfill-toolbar-inner">
        <select v-model="tenantFilter" title="企业">
          <option value="">全部企业</option>
          <option v-for="tenant in tenants" :key="tenant.id" :value="tenant.id">
            {{ tenant.name }}
          </option>
        </select>
        <input v-model="filterDate" type="date" title="检测日期">
        <select v-model="sourceFilter" title="来源">
          <option value="">全部来源</option>
          <option value="tenant_monitor">GEO 监测</option>
          <option value="lead_diagnosis">售前诊断</option>
        </select>
        <select v-model="platformFilter" title="平台">
          <option value="">全部平台</option>
          <option v-for="platform in platformFilterOptions" :key="platform.code" :value="platform.code">
            {{ platform.name }}
          </option>
        </select>
        <select
          v-model="keywordGroupFilter"
          class="snapshot-backfill-group-select"
          :disabled="!keywordGroupOptions.length"
          :title="tenantFilter ? '词组' : '请先选择企业'"
        >
          <option value="">{{ tenantFilter ? '全部词组' : '先选企业' }}</option>
          <option
            v-for="(group, index) in keywordGroupOptions"
            :key="keywordGroupSelectValue(group, index)"
            :value="keywordGroupSelectValue(group, index)"
            :title="formatKeywordGroupDetailHint(group)"
          >
            {{ keywordGroupDisplayName(group, index) }}
          </option>
        </select>
        <select
          v-model="keywordFilter"
          class="snapshot-backfill-keyword-input"
          :disabled="!monitorKeywordOptions.length"
          :title="tenantFilter ? '监测词' : '请先选择企业'"
        >
          <option value="">{{ tenantFilter ? '全部监测词' : '先选企业' }}</option>
          <option v-for="keyword in monitorKeywordOptions" :key="keyword" :value="keyword">
            {{ keyword }}
          </option>
        </select>
        <label class="snapshot-backfill-toolbar-check">
          <input v-model="pendingOnly" type="checkbox">
          仅待补录
        </label>
        <div class="snapshot-backfill-toolbar-actions">
          <span v-if="loading" class="snapshot-backfill-loading-dot">加载中…</span>
          <button type="button" class="filter-reset-btn tiny-btn" @click="resetFilters">重置</button>
          <button type="button" class="filter-reset-btn tiny-btn" :disabled="loading" @click="loadItems">
            <RefreshCw :size="14" />
            刷新
          </button>
        </div>
      </div>
    </div>

    <div v-if="hasActiveFilters" class="snapshot-backfill-chips">
      <span v-if="filterDate" class="snapshot-backfill-chip">检测日 {{ filterDate }}</span>
      <span v-if="sourceFilter" class="snapshot-backfill-chip">
        {{ sourceFilter === 'lead_diagnosis' ? '售前诊断' : 'GEO 监测' }}
      </span>
      <span v-if="platformFilter" class="snapshot-backfill-chip">
        {{ platformLabelMap[platformFilter] || platformFilter }}
      </span>
      <span v-if="keywordGroupSummary" class="snapshot-backfill-chip">词组 {{ keywordGroupSummary }}</span>
      <span v-if="keywordFilter" class="snapshot-backfill-chip">监测词 {{ keywordFilter }}</span>
      <small>通知铃铛可直达对应子任务</small>
    </div>

    <div v-if="loading" class="mini-empty">加载中…</div>
    <div v-else-if="!items.length" class="mini-empty snapshot-backfill-empty">
      当前筛选下没有可补录/可覆盖项。请调整企业、检测日期、来源或平台，或取消「仅待补录」。
    </div>
    <template v-else>
      <div class="snapshot-backfill-list">
        <article
          v-for="item in items"
          :key="item.subtask_id"
          class="snapshot-backfill-card"
          @click="openDetail(item)"
        >
          <div class="snapshot-backfill-card-head">
            <span class="snapshot-backfill-tag source">{{ sourceLabel(item) }}</span>
            <span
              class="snapshot-backfill-tag"
              :class="{ pending: item.needs_backfill, done: item.has_answer && !item.needs_backfill }"
            >
              {{ statusLabel(item) }}
            </span>
            <PlatformBadge :code="item.platform" size="xs" />
          </div>
          <p class="snapshot-backfill-card-tenant">{{ scopeLabel(item) }}</p>
          <h3 class="snapshot-backfill-card-prompt">{{ item.prompt }}</h3>
          <dl class="snapshot-backfill-metrics">
            <div class="snapshot-backfill-metric">
              <dt>词组</dt>
              <dd>{{ item.keyword_group || item.monitor_keywords || '—' }}</dd>
            </div>
            <div v-if="item.region_label && item.region_label !== '全部区域'" class="snapshot-backfill-metric">
              <dt>地区</dt>
              <dd>{{ item.region_label }}</dd>
            </div>
            <div class="snapshot-backfill-metric" :class="rankMetricClass(item)">
              <dt>排名</dt>
              <dd>{{ formatMonitorSubtaskRank(item) }}</dd>
            </div>
            <div class="snapshot-backfill-metric">
              <dt>批次</dt>
              <dd>{{ detectTimeLabel(item) }}</dd>
            </div>
          </dl>
          <p v-if="item.error_message" class="snapshot-backfill-card-error">{{ item.error_message }}</p>
          <div v-if="canSubmitBackfill" class="snapshot-backfill-card-actions" @click.stop>
            <button
              type="button"
              class="snapshot-backfill-card-action"
              :class="{ 'is-overwrite': !item.needs_backfill }"
              @click="openBackfill(item)"
            >
              <Upload :size="14" />
              {{ actionLabel(item) }}
            </button>
            <button
              v-if="item.needs_backfill"
              type="button"
              class="snapshot-backfill-card-action is-dismiss"
              @click="dismissItem(item)"
            >
              <EyeOff :size="14" />
              忽略
            </button>
          </div>
        </article>
      </div>
      <div
        v-if="hasMore"
        ref="loadMoreSentinel"
        class="snapshot-backfill-load-more"
      >
        <span v-if="loadingMore">加载更多…</span>
        <span v-else>继续下滑加载更多</span>
      </div>
      <p v-else-if="items.length" class="snapshot-backfill-end">已加载全部 {{ totalCount }} 条</p>
    </template>

    <SnapshotBackfillDetailDrawer
      v-model:visible="detailVisible"
      :loading="detailLoading"
      :item="detailItem"
      :subtask="detailSubtask"
      :can-submit="canSubmitBackfill"
      @backfill="openBackfillFromDetail"
      @undismiss="undismissFromDetail"
    />

    <SnapshotBackfillDialog
      v-model:visible="backfillVisible"
      :subtask="backfillTarget"
      @success="handleSuccess"
    />
  </section>
</template>
