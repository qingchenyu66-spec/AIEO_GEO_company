<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { ElMessage, ElTooltip } from 'element-plus'
import { HelpCircle, MoreHorizontal } from '@lucide/vue'
import type { BrandAsset, BrandCompetitor } from '../../../services/brand'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import TenantLogoField from '../../../components/TenantLogoField.vue'
import RegionMultiSelect from '../components/RegionMultiSelect.vue'
import TenantCreditPanel from '../components/TenantCreditPanel.vue'
import { useAuthStore } from '../../../stores/auth'
import { useBrandAudit } from '../composables/useBrandAudit'
import { keywordGroupMonitorKeywords, normalizePlatformSelections, platformSelectionCodes } from '../../../services/brand'
import { PortalNavigateKey } from '../injectionKeys'
import { previewQueryFields } from '../customerPreview'
import { prefetchCustomerPreviewMenus } from '../previewMenusCache'
import { extractErrorDetail } from '../../../utils/requestError'

function platformSelectionCount(group: { platforms?: unknown[] }) {
  return platformSelectionCodes((group.platforms || []) as never).length
}

const PLATFORM_MODE_LABELS: Record<string, string> = {
  standard: '快速',
  reasoning: '深度',
  // 历史数据兜底展示（弹窗仍用「深度思考」全称）
  search: '快速',
  reasoning_search: '深度',
}

function platformModeLabel(group: { platforms?: unknown[] }, code: string) {
  const hit = normalizePlatformSelections((group.platforms || []) as never).find(item => item.code === code)
  if (!hit) return ''
  return PLATFORM_MODE_LABELS[hit.mode] || PLATFORM_MODE_LABELS.standard
}

function uniqueNonEmpty(values: Array<string | null | undefined>) {
  const seen = new Set<string>()
  const rows: string[] = []
  for (const value of values) {
    const text = String(value || '').trim()
    if (!text) continue
    const key = text.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    rows.push(text)
  }
  return rows
}

const props = defineProps<{
  customerConfigEmbed?: boolean
}>()

const emit = defineEmits<{
  'brand-updated': [asset: BrandAsset | null, competitors: BrandCompetitor[]]
}>()

const auth = useAuthStore()
const portalNavigate = inject(PortalNavigateKey)!
const openingPreview = ref(false)

function navigateToReportCenter(reportId: number, tenantId: number) {
  if (!auth.allowedMenus.some(menu => menu.menu_code === 'platform.reports')) return
  portalNavigate('platform.reports', false, {
    reportId: String(reportId),
    tenantId: String(tenantId),
  })
}

async function openCustomerPreview(tenant: { id: number; name: string }) {
  if (openingPreview.value) return
  await loadEnterpriseList()
  if (!tenants.value.some(item => item.id === tenant.id)) {
    ElMessage.warning('该企业已不存在或无权查看，列表已刷新')
    return
  }
  openingPreview.value = true
  try {
    // 先拉菜单再进预览，侧栏进门就有配置名，禁止空窗/硬编码闪名
    await prefetchCustomerPreviewMenus(tenant.id)
    portalNavigate('customer.workspace', false, previewQueryFields(tenant.id, tenant.name))
  } catch (error: unknown) {
    ElMessage.error(extractErrorDetail(error) || '客户菜单加载失败，无法进入预览')
  } finally {
    openingPreview.value = false
  }
}

const {
  platformLabelMap,
  formatPlatformLabels,
  loadCatalogPlatforms,
  groupHasPlatform,
  onPlatformCheckClick,
  removeGroupPlatform,
  modeDialogVisible,
  modeDialogForm,
  confirmModeDialog,
  cancelModeDialog,
  enterpriseDetailMode,
  enterpriseDetailTab,
  enterpriseInfoDialog,
  enterpriseInfoLoading,
  enterpriseInfoTenant,
  enterpriseInfoAsset,
  enterpriseInfoCompetitors,
  enterpriseFilters,
  tenantDialog,
  creatingDraftTenant,
  tenantForm,
  pendingTenantLogoPreview,
  pendingTenantLogoFileName,
  editingTenantLogoSrc,
  onTenantLogoPick,
  clearPendingTenantLogo,
  tenantTransferDialog,
  tenantTransferTarget,
  tenantTransferOwnerId,
  tenantSalesOwners,
  loadingTenantSalesOwners,
  transferringTenantOwner,
  canTransferTenantOwner,
  canFilterBySales,
  showOwnerOnEnterpriseList,
  tenantSalesFilterOptions,
  knowledgeFiles,
  loadingKnowledgeFiles,
  competitorRows,
  keywordGroupRows,
  brandWordGroupRows,
  competitorNameInput,
  loadingBrand,
  brandForm,
  tenants,
  filteredTenants,
  pagedTenants,
  enterprisePage,
  enterpriseTotalPages,
  changeEnterprisePage,
  enterpriseFormServiceActive,
  brandAsset,
  canSubmitBrandAssetProfile,
  enterpriseFormServiceLabel,
  visibleEnterpriseTabs,
  canViewEnterpriseTab,
  canEditEnterpriseTab,
  canEditRegions,
  canEditModels,
  editableCatalogPlatforms,
  canCreateTenant,
  canEditTenantList,
  isTenantExpired,
  isTenantPending,
  tenantServiceLabel,
  canStopTenantService,
  canRestoreTenantService,
  canPurgeTenant,
  stopTenantActionLabel,
  tenantServicePeriod,
  tenantMonitorLabel,
  tenantBillingLabel,
  tenantOwnerLabel,
  editingGroupIndex,
  editingBrandWordGroupIndex,
  keywordGroupDisplayName,
  brandWordGroupDisplayName,
  startEditGroupName,
  finishEditGroupName,
  cancelEditGroupName,
  startEditBrandWordGroupName,
  finishEditBrandWordGroupName,
  cancelEditBrandWordGroupName,
  addKeywordGroup,
  removeKeywordGroup,
  addBrandWordGroup,
  removeBrandWordGroup,
  removeExposureTerm,
  commitMonitorKeywordInput,
  handleMonitorKeywordPaste,
  removeMonitorKeyword,
  commitExposureTermInput,
  handleExposureTermPaste,
  addScheduleTime,
  removeScheduleTime,
  loadEnterpriseList,
  loadResubmitDraftFromRoute,
  openEnterpriseDetail,
  openEnterpriseInfo,
  backToEnterpriseList,
  submitBrandAsset,
  submitBrandWordGroups,
  goNextFromTenantDialog,
  removeTenant,
  purgeTenantThoroughly,
  restoreTenantService,
  openTenantTransferDialog,
  submitTenantTransfer,
  addCompetitorTag,
  removeCompetitorRow,
  formatFileSize,
  resetDetailMode,
  knowledgePreviewVisible,
  knowledgePreviewFile,
  knowledgePreviewUrl,
  knowledgePreviewLoading,
  knowledgePreviewError,
  canDeleteKnowledgeFiles,
  canUploadKnowledgeFiles,
  uploadingKnowledgeFile,
  knowledgeUploadDialogVisible,
  knowledgeUploadTenant,
  openKnowledgeUploadDialog,
  openEnterpriseDetailFiles,
  handleKnowledgeUploadInput,
  previewKnowledgeFile,
  closeKnowledgePreview,
  downloadKnowledgeFileItem,
  removeKnowledgeFile,
  reportDialog,
  reportDialogTenant,
  reportGenerating,
  reportTitle,
  canGenerateEnterpriseReport,
  canExportPeriodReport,
  openReportDialog,
  submitEnterpriseReport,
  periodExportDialog,
  periodExportTenant,
  periodExportKind,
  periodExportKinds,
  periodExportStart,
  periodExportEnd,
  periodExporting,
  periodExportProgress,
  periodExportHint,
  openPeriodExportDialog,
  submitPeriodExport,
  isEnterprisePinned,
  pinEnterprise,
  unpinEnterprise,
  initCustomerEnterpriseConfig,
  customerDailyEstimate,
} = useBrandAudit({
  customerEnterpriseMode: props.customerConfigEmbed,
  onBrandUpdated: (asset, competitors) => emit('brand-updated', asset, competitors),
  navigateToReportCenter,
})

const knowledgeUploadInputRef = ref<HTMLInputElement | null>(null)
const knowledgeUploadTargetId = ref<number | null>(null)

function pickKnowledgeUpload(tenantId: number) {
  knowledgeUploadTargetId.value = tenantId
  knowledgeUploadInputRef.value?.click()
}

async function onKnowledgeUploadInput(event: Event) {
  const tenantId = knowledgeUploadTargetId.value
  if (!tenantId) return
  try {
    await handleKnowledgeUploadInput(event, tenantId)
  } finally {
    knowledgeUploadTargetId.value = null
  }
}

function onKnowledgeUploadDialogClosed() {
  knowledgeUploadTenant.value = null
}

/** 详情弹窗只展示词组里的监测词/露出词，不展示资产级强制并入的企业全称 */
const enterpriseInfoMonitorKeywords = computed(() => {
  const asset = enterpriseInfoAsset.value
  if (!asset) return []
  const fromGroups = (asset.keyword_groups || []).flatMap(group => keywordGroupMonitorKeywords(group))
  if (fromGroups.length) return uniqueNonEmpty(fromGroups)
  const company = String(asset.company_full_name || '').trim().toLowerCase()
  const brand = String(asset.brand_name || '').trim().toLowerCase()
  return uniqueNonEmpty(asset.monitor_keywords || []).filter(item => {
    const key = item.toLowerCase()
    return key !== company && key !== brand
  })
})

const enterpriseInfoExposureTerms = computed(() => {
  const asset = enterpriseInfoAsset.value
  if (!asset) return []
  const fromGroups = (asset.keyword_groups || []).flatMap(group => group.exposure_terms || [])
  if (fromGroups.length) return uniqueNonEmpty(fromGroups)
  return uniqueNonEmpty(asset.aliases || [])
})

const customerDailyCredits = computed(() => {
  const raw = Number((customerDailyEstimate.value || {}).credits_per_day)
  return Number.isFinite(raw) ? raw : null
})

const customerDailyEstimateMeta = computed(() => {
  const estimate = customerDailyEstimate.value || {}
  const keywordCount = Number(estimate.keyword_count)
  const platformCount = Number(estimate.platform_count)
  const scheduleSlots = Number(estimate.schedule_slots)
  const parts: string[] = []
  if (Number.isFinite(keywordCount)) parts.push(`${keywordCount} 词`)
  if (Number.isFinite(platformCount)) parts.push(`${platformCount} 端`)
  if (Number.isFinite(scheduleSlots)) parts.push(`${scheduleSlots} 次/日`)
  return parts.join(' · ')
})

const showCustomerDailyEstimate = computed(() => (
  props.customerConfigEmbed
  && customerDailyCredits.value != null
  && ['keywords', 'schedule', 'brand_words'].includes(enterpriseDetailTab.value)
))

onMounted(async () => {
  if (props.customerConfigEmbed) {
    void initCustomerEnterpriseConfig()
    return
  }
  await loadEnterpriseList()
  void loadCatalogPlatforms()
  void loadResubmitDraftFromRoute()
})

defineExpose({ resetDetailMode, backToEnterpriseList, loadEnterpriseList })
</script>

<template>
  <section :class="customerConfigEmbed ? 'brand-page customer-config-embed' : 'brand-page'">
    <article v-if="!customerConfigEmbed && !enterpriseDetailMode" class="panel enterprise-list-panel">
      <!-- 2026-07-31 - 列表头与页头双标题重复 - 去面板头，动作并入筛选行右侧 -->
      <div class="enterprise-filter-bar">
        <label class="enterprise-filter-keyword">
          <span>企业名称</span>
          <input v-model="enterpriseFilters.keyword" placeholder="输入企业名称 / 编码筛选" />
        </label>
        <label>
          <span>服务状态</span>
          <select v-model="enterpriseFilters.expiry">
            <option value="all">全部企业</option>
            <option value="active">服务中</option>
            <option value="pending">未开始服务</option>
            <option value="expired">服务已到期</option>
            <option value="stopped">已停止服务</option>
          </select>
        </label>
        <label>
          <span>企业类型</span>
          <select v-model="enterpriseFilters.billing_mode">
            <option value="all">全部类型</option>
            <option value="hosted">平台托管</option>
            <option value="credit">算力自助</option>
          </select>
        </label>
        <label v-if="canFilterBySales">
          <span>归属销售</span>
          <select v-model="enterpriseFilters.owner_user_id">
            <option value="all">全部销售</option>
            <option value="none">未指定</option>
            <option v-for="owner in tenantSalesFilterOptions" :key="owner.id" :value="owner.id">{{ owner.name }}</option>
          </select>
        </label>
        <button
          type="button"
          class="enterprise-filter-reset"
          @click="enterpriseFilters.keyword = ''; enterpriseFilters.expiry = 'active'; enterpriseFilters.billing_mode = 'all'; enterpriseFilters.owner_user_id = 'all'"
        >
          重置
        </button>
        <div class="enterprise-filter-actions">
          <button type="button" class="filter-reset-btn" :disabled="loadingBrand" @click="loadEnterpriseList">刷新企业</button>
          <button v-if="canCreateTenant" type="button" class="primary-btn small-btn" @click="tenantDialog = true">新增企业</button>
        </div>
      </div>
      <div class="enterprise-list-summary">
        <span>共 {{ filteredTenants.length }} 家企业</span>
        <span v-if="filteredTenants.length">第 {{ enterprisePage }} / {{ enterpriseTotalPages }} 页</span>
        <span v-if="loadingBrand">列表刷新中…</span>
      </div>
      <div class="enterprise-table">
        <div
          v-for="tenant in pagedTenants"
          :key="tenant.id"
          class="enterprise-row"
          :class="{ stopped: !tenant.status || isTenantExpired(tenant) || isTenantPending(tenant) }"
        >
          <div class="enterprise-main">
            <b>{{ tenant.name }}</b>
            <small class="enterprise-meta-line">
              {{ tenantServicePeriod(tenant) }}
              <template v-if="showOwnerOnEnterpriseList"> · 销售 {{ tenantOwnerLabel(tenant) }}</template>
            </small>
          </div>
          <div class="enterprise-metrics enterprise-metrics-inline">
            <span>
              <small>服务状态</small>
              <b class="status-pill" :class="{ dark: !tenant.status || isTenantExpired(tenant) || isTenantPending(tenant) }">{{ tenantServiceLabel(tenant) }}</b>
            </span>
            <span>
              <small>企业类型</small>
              <b>{{ tenantBillingLabel(tenant) }}</b>
            </span>
            <span>
              <small>自动监测</small>
              <b>{{ tenantMonitorLabel(tenant) }}</b>
            </span>
          </div>
          <div class="enterprise-actions">
            <!-- 2026-07-30 - 按线上卡片布局收敛操作 - 主钮留查看/详情/编辑，其余进三点 -->
            <button type="button" class="filter-search-btn" :disabled="openingPreview" @click="openCustomerPreview(tenant)">
              {{ openingPreview ? '加载中…' : '查看客户端' }}
            </button>
            <button type="button" class="filter-reset-btn" @click="openEnterpriseInfo(tenant)">详情</button>
            <button v-if="canEditTenantList" type="button" class="filter-reset-btn" @click="openEnterpriseDetail(tenant)">编辑</button>
            <el-dropdown trigger="click">
              <button type="button" class="icon-action enterprise-more-btn" title="更多操作" aria-label="更多操作">
                <MoreHorizontal />
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-if="!isEnterprisePinned(tenant)"
                    @click="pinEnterprise(tenant)"
                  >置顶</el-dropdown-item>
                  <el-dropdown-item
                    v-else
                    @click="unpinEnterprise(tenant)"
                  >取消置顶</el-dropdown-item>
                  <el-dropdown-item v-if="canTransferTenantOwner" @click="openTenantTransferDialog(tenant)">转移</el-dropdown-item>
                  <el-dropdown-item v-if="canGenerateEnterpriseReport" @click="openReportDialog(tenant)">报告</el-dropdown-item>
                  <el-dropdown-item v-if="canExportPeriodReport" @click="openPeriodExportDialog(tenant)">导出报告</el-dropdown-item>
                  <el-dropdown-item
                    v-if="canUploadKnowledgeFiles"
                    @click="openKnowledgeUploadDialog(tenant)"
                  >上传资料</el-dropdown-item>
                  <el-dropdown-item
                    v-if="canStopTenantService(tenant)"
                    :divided="true"
                    @click="removeTenant(tenant)"
                  >{{ stopTenantActionLabel(tenant) }}</el-dropdown-item>
                  <el-dropdown-item
                    v-else-if="canRestoreTenantService(tenant)"
                    :divided="true"
                    @click="restoreTenantService(tenant)"
                  >恢复服务</el-dropdown-item>
                  <el-dropdown-item
                    v-if="canPurgeTenant()"
                    :divided="canStopTenantService(tenant) || canRestoreTenantService(tenant) || canTransferTenantOwner || canGenerateEnterpriseReport"
                    class="enterprise-action-danger"
                    @click="purgeTenantThoroughly(tenant)"
                  >彻底删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
        <div v-if="!loadingBrand && !filteredTenants.length" class="mini-empty enterprise-empty">暂无符合筛选条件的企业。</div>
        <div v-if="enterpriseTotalPages > 1" class="log-pagination">
          <span class="log-pagination-meta">每页 10 条</span>
          <div class="log-pagination-actions">
            <button
              type="button"
              class="filter-reset-btn tiny-btn"
              :disabled="enterprisePage <= 1"
              @click="changeEnterprisePage(enterprisePage - 1)"
            >
              上一页
            </button>
            <button
              type="button"
              class="filter-reset-btn tiny-btn"
              :disabled="enterprisePage >= enterpriseTotalPages"
              @click="changeEnterprisePage(enterprisePage + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </div>
    </article>

    <article v-else class="panel brand-asset-panel">
      <div v-if="!customerConfigEmbed" class="panel-head">
        <div>
          <h2>企业资料与监控配置</h2>
          <p>平台运营端维护客户企业、品牌词和竞品库，系统按配置定时提交监测任务。</p>
        </div>
        <div class="detail-actions">
          <button class="filter-reset-btn" @click="backToEnterpriseList">返回列表</button>
          <!-- 2026-08-18 - 草稿点页签保存就进审批 - 新建只走右上角这一处提交 -->
          <button
            v-if="(canEditEnterpriseTab(enterpriseDetailTab) || (enterpriseDetailTab === 'profile' && canEditRegions)) && enterpriseDetailTab !== 'credit'"
            class="primary-btn small-btn"
            :disabled="loadingBrand || !canSubmitBrandAssetProfile"
            @click="() => submitBrandAsset()"
          >保存当前配置</button>
        </div>
      </div>
      <div v-else class="panel-head compact-head">
        <button
          v-if="canEditEnterpriseTab(enterpriseDetailTab) || (enterpriseDetailTab === 'profile' && canEditRegions)"
          class="primary-btn small-btn"
          :disabled="loadingBrand || !canSubmitBrandAssetProfile"
          @click="() => submitBrandAsset()"
        >保存当前配置</button>
        <div
          v-if="showCustomerDailyEstimate"
          class="credit-daily-estimate"
          title="按当前监测词、平台与计划估算，保存后刷新"
        >
          <span class="credit-daily-estimate-label">日预估算力</span>
          <strong>{{ customerDailyCredits }}</strong>
          <span v-if="customerDailyEstimateMeta" class="credit-daily-estimate-meta">{{ customerDailyEstimateMeta }}</span>
        </div>
      </div>
      <div class="enterprise-detail-tabs">
        <button v-for="tab in visibleEnterpriseTabs" :key="tab.code" :class="{ active: enterpriseDetailTab === tab.code }" @click="enterpriseDetailTab = tab.code">{{ tab.name }}</button>
      </div>
      <div v-if="enterpriseDetailTab === 'profile'" class="brand-form-grid">
        <template v-if="customerConfigEmbed">
          <label class="form-field-full"><span>企业名称</span><div class="readonly-status">{{ brandForm.company_full_name || '—' }}</div></label>
          <label v-if="canEditRegions" class="region-field form-field-full">
            <span>服务地区</span>
            <RegionMultiSelect v-model="brandForm.region_codes" :disabled="!canEditRegions" />
          </label>
        </template>
        <template v-else>
        <label><span>企业全称</span><input v-model="brandForm.company_full_name" :disabled="!canEditEnterpriseTab('profile')" placeholder="例如 北京艾亿欧科技有限公司" /></label>
        <label><span>服务开始日期</span><input v-model="brandForm.service_start_date" :disabled="!canEditEnterpriseTab('profile')" type="date" /></label>
        <label><span>服务结束日期</span><input v-model="brandForm.service_end_date" :disabled="!canEditEnterpriseTab('profile')" type="date" /></label>
        <label><span>官网 / 主站</span><input v-model="brandForm.official_url" :disabled="!canEditEnterpriseTab('profile')" placeholder="https://..." /></label>
        <label>
          <span>企业状态</span>
          <div class="readonly-status" :class="{ stopped: !enterpriseFormServiceActive }">{{ enterpriseFormServiceLabel }}</div>
        </label>
        <label>
          <span>
            商品卡
            <el-tooltip content="开通后自动给该企业客户账号加上「商品卡」菜单；日常监测词组需勾选手机端平台才有数据" placement="top">
              <HelpCircle :size="14" />
            </el-tooltip>
          </span>
          <!-- 2026-09-01 - 与企业状态并排；字符串值避免 select 布尔回填错位 -->
          <select
            :value="brandForm.goods_card_enabled ? '1' : '0'"
            :disabled="!canEditEnterpriseTab('profile')"
            @change="brandForm.goods_card_enabled = ($event.target as HTMLSelectElement).value === '1'"
          >
            <option value="0">关闭</option>
            <option value="1">开通</option>
          </select>
        </label>
        <label v-if="canEditRegions" class="region-field form-field-full">
          <span>服务地区</span>
          <RegionMultiSelect
            v-model="brandForm.region_codes"
            :disabled="!canEditRegions"
          />
        </label>
        <label v-if="canEditTenantList" class="form-field-full">
          <span>企业 Logo</span>
          <TenantLogoField
            :preview-src="pendingTenantLogoPreview || editingTenantLogoSrc || undefined"
            :file-name="pendingTenantLogoFileName"
            @pick="onTenantLogoPick"
            @clear="clearPendingTenantLogo"
          />
        </label>
        <label class="form-field-full"><span>品牌说明</span><textarea v-model="brandForm.description" :disabled="!canEditEnterpriseTab('profile')" rows="4" placeholder="用于内部识别，不直接展示给客户"></textarea></label>
        </template>
      </div>
      <div v-if="!creatingDraftTenant && enterpriseDetailTab === 'profile' && (canEditEnterpriseTab('profile') || canEditRegions)" class="section-save-actions keyword-save-actions">
        <button class="filter-search-btn" :disabled="loadingBrand || !canSubmitBrandAssetProfile" @click="submitBrandAsset('企业资料已保存')">保存企业资料</button>
      </div>
      <section v-if="enterpriseDetailTab === 'keywords'" class="keyword-group-panel">
        <div class="panel-head">
          <div>
            <h2>监测词组配置</h2>
            <p>一个词组可配置多个监测关键词、多个露出词，并<strong>单独选择监测平台</strong>。<strong>监测关键词即检测问题</strong>，系统不再套用模板生成；<strong>露出词</strong>用于在 AI 推荐列表中匹配品牌排名。定时任务按各词组勾选的平台提交检测。</p>
          </div>
          <button v-if="canEditEnterpriseTab('keywords')" class="filter-search-btn" @click="addKeywordGroup">新增词组</button>
        </div>
        <div class="keyword-group-list">
          <div v-for="(group, index) in keywordGroupRows" :key="group.id || `kw-${index}`" class="keyword-group-card">
            <div class="keyword-group-toolbar">
              <div class="keyword-group-title">
                <input
                  v-if="editingGroupIndex === index && canEditEnterpriseTab('keywords')"
                  :id="`keyword-group-name-${index}`"
                  class="keyword-group-name-input"
                  :value="group.name || keywordGroupDisplayName(group, index)"
                  maxlength="100"
                  @keydown.enter="finishEditGroupName(group, index, ($event.target as HTMLInputElement).value)"
                  @keydown.esc.prevent="cancelEditGroupName"
                  @blur="finishEditGroupName(group, index, ($event.target as HTMLInputElement).value)"
                />
                <button
                  v-else
                  type="button"
                  class="keyword-group-name"
                  :class="{ readonly: !canEditEnterpriseTab('keywords') }"
                  :disabled="!canEditEnterpriseTab('keywords')"
                  @click="startEditGroupName(index)"
                >
                  {{ keywordGroupDisplayName(group, index) }}
                </button>
              </div>
              <div class="keyword-group-actions">
                <label class="keyword-group-status">
                  <span>状态</span>
                  <select v-model="group.status" :disabled="!canEditEnterpriseTab('keywords')">
                    <option :value="true">启用</option>
                    <option :value="false">停用</option>
                  </select>
                </label>
                <button
                  v-if="canEditEnterpriseTab('keywords')"
                  type="button"
                  class="danger-text-btn keyword-group-delete-btn"
                  @click="removeKeywordGroup(index)"
                >
                  删除词组
                </button>
              </div>
            </div>
            <div class="keyword-group-fields">
              <div class="keyword-field monitor-keyword-field">
                <span class="keyword-field-label">监测关键词（{{ keywordGroupMonitorKeywords(group).length }}）</span>
                <div class="keyword-tag-box">
                  <i v-for="(term, keywordIndex) in keywordGroupMonitorKeywords(group)" :key="`${index}-kw-${keywordIndex}-${term}`">
                    {{ term }}
                    <button v-if="canEditEnterpriseTab('keywords')" type="button" @click="removeMonitorKeyword(group, keywordIndex)">×</button>
                  </i>
                  <input
                    placeholder="输入后回车添加，支持粘贴多行批量添加"
                    :disabled="!canEditEnterpriseTab('keywords')"
                    @keyup.enter="commitMonitorKeywordInput(group, $event)"
                    @blur="commitMonitorKeywordInput(group, $event)"
                    @paste="handleMonitorKeywordPaste(group, $event)"
                  />
                </div>
              </div>
              <div class="keyword-field exposure-keyword-field">
                <span class="keyword-field-label">露出词</span>
                <div class="keyword-tag-box">
                  <i v-for="(term, termIndex) in group.exposure_terms" :key="`${index}-${term}`">
                    {{ term }}
                    <button v-if="canEditEnterpriseTab('keywords')" type="button" @click="removeExposureTerm(group, termIndex)">×</button>
                  </i>
                  <input
                    placeholder="输入后回车添加，支持粘贴多行批量添加"
                    :disabled="!canEditEnterpriseTab('keywords')"
                    @keyup.enter="commitExposureTermInput(group, $event)"
                    @blur="commitExposureTermInput(group, $event)"
                    @paste="handleExposureTermPaste(group, $event)"
                  />
                </div>
              </div>
              <div v-if="canEditModels" class="keyword-field keyword-group-platform-field">
                <span class="keyword-field-label">监测平台（{{ platformSelectionCount(group) }}）</span>
                <div v-if="!editableCatalogPlatforms.length" class="mini-empty compact-empty">当前职位未配置可勾选平台</div>
                <div v-else class="platform-check-grid compact">
                  <label
                    v-for="platform in editableCatalogPlatforms"
                    :key="`${index}-${platform.code}`"
                    class="platform-check"
                    :class="{
                      'is-disabled': 'selectable' in platform && !platform.selectable && !groupHasPlatform(group, platform.code),
                      'is-unavailable': 'labels' in platform && (platform.labels || []).includes('无服务'),
                      'is-delisted': 'labels' in platform && (platform.labels || []).includes('已下架'),
                    }"
                    @click.prevent="onPlatformCheckClick(index, platform.code)"
                  >
                    <input
                      type="checkbox"
                      tabindex="-1"
                      :checked="groupHasPlatform(group, platform.code)"
                      :disabled="!canEditModels || !canEditEnterpriseTab('keywords') || ('selectable' in platform && !platform.selectable && !groupHasPlatform(group, platform.code))"
                    />
                    <PlatformBadge
                      :code="platform.code"
                      size="sm"
                      :label="'name' in platform && platform.name ? platform.name : undefined"
                    />
                    <small
                      v-if="groupHasPlatform(group, platform.code)"
                      class="platform-mode-tag"
                      :title="'点击整块可修改模式'"
                    >
                      {{ platformModeLabel(group, platform.code) }}
                    </small>
                    <small v-if="'labels' in platform && platform.labels?.length" class="platform-status-tag">{{ platform.labels.join('·') }}</small>
                    <button
                      v-if="canEditModels && canEditEnterpriseTab('keywords') && groupHasPlatform(group, platform.code)"
                      type="button"
                      class="platform-uncheck-btn"
                      title="取消勾选"
                      @click.stop.prevent="removeGroupPlatform(index, platform.code)"
                    >
                      ×
                    </button>
                  </label>
                </div>
              </div>
              <div v-else-if="platformSelectionCount(group)" class="keyword-field keyword-group-platform-field">
                <span class="keyword-field-label">监测平台（{{ platformSelectionCount(group) }}）</span>
                <div class="platform-check-grid compact readonly">
                  <span
                    v-for="code in platformSelectionCodes(group.platforms || [])"
                    :key="`${index}-${code}-ro`"
                    class="platform-check readonly"
                  >
                    <PlatformBadge :code="code" size="sm" :label="platformLabelMap[code]" />
                    <small class="platform-mode-tag">{{ platformModeLabel(group, code) }}</small>
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div v-if="!keywordGroupRows.length" class="mini-empty">暂无监测词组，请先新增一个。</div>
        </div>
        <div v-if="!creatingDraftTenant" class="section-save-actions keyword-save-actions">
          <button v-if="canEditEnterpriseTab('keywords')" class="filter-search-btn" :disabled="loadingBrand || !canSubmitBrandAssetProfile" @click="submitBrandAsset('监测词配置已保存')">保存监测词配置</button>
        </div>
      </section>
      <section v-if="enterpriseDetailTab === 'brand_words'" class="keyword-group-panel">
        <div class="panel-head">
          <div>
            <h2>品牌词组配置</h2>
            <p>配置品牌词、监测平台与<strong>运行时间</strong>：仅本次（保存后立刻跑一轮）或周（每周一约 9:00）。匹配别名取自企业资料，无需单独配置露出词。</p>
          </div>
          <button v-if="canEditEnterpriseTab('brand_words')" class="filter-search-btn" @click="addBrandWordGroup">新增词组</button>
        </div>
        <div class="keyword-group-list">
          <div v-for="(group, index) in brandWordGroupRows" :key="group.id || `bw-${index}`" class="keyword-group-card">
            <div class="keyword-group-toolbar">
              <div class="keyword-group-title">
                <input
                  v-if="editingBrandWordGroupIndex === index && canEditEnterpriseTab('brand_words')"
                  :id="`brand-word-group-name-${index}`"
                  class="keyword-group-name-input"
                  :value="group.name || brandWordGroupDisplayName(group, index)"
                  maxlength="100"
                  @keydown.enter="finishEditBrandWordGroupName(group, index, ($event.target as HTMLInputElement).value)"
                  @keydown.esc.prevent="cancelEditBrandWordGroupName"
                  @blur="finishEditBrandWordGroupName(group, index, ($event.target as HTMLInputElement).value)"
                />
                <button
                  v-else
                  type="button"
                  class="keyword-group-name"
                  :class="{ readonly: !canEditEnterpriseTab('brand_words') }"
                  :disabled="!canEditEnterpriseTab('brand_words')"
                  @click="startEditBrandWordGroupName(index)"
                >
                  {{ brandWordGroupDisplayName(group, index) }}
                </button>
              </div>
              <div class="keyword-group-actions">
                <label class="keyword-group-status">
                  <span>运行时间</span>
                  <select v-model="group.run_mode" :disabled="!canEditEnterpriseTab('brand_words')">
                    <option value="once">仅本次</option>
                    <option value="weekly">周</option>
                  </select>
                </label>
                <label v-if="customerConfigEmbed && group.run_mode === 'once'" class="keyword-group-status run-immediate-field">
                  <span>立即跑</span>
                  <input
                    v-model="group.run_immediately"
                    type="checkbox"
                    :disabled="!canEditEnterpriseTab('brand_words')"
                  />
                </label>
                <label class="keyword-group-status">
                  <span>状态</span>
                  <select v-model="group.status" :disabled="!canEditEnterpriseTab('brand_words')">
                    <option :value="true">启用</option>
                    <option :value="false">停用</option>
                  </select>
                </label>
                <button
                  v-if="canEditEnterpriseTab('brand_words')"
                  type="button"
                  class="danger-text-btn keyword-group-delete-btn"
                  @click="removeBrandWordGroup(index)"
                >
                  删除词组
                </button>
              </div>
            </div>
            <div class="keyword-group-fields">
              <div class="keyword-field monitor-keyword-field">
                <span class="keyword-field-label">品牌词（{{ keywordGroupMonitorKeywords(group).length }}）</span>
                <div class="keyword-tag-box">
                  <i v-for="(term, keywordIndex) in keywordGroupMonitorKeywords(group)" :key="`bw-${index}-kw-${keywordIndex}-${term}`">
                    {{ term }}
                    <button v-if="canEditEnterpriseTab('brand_words')" type="button" @click="removeMonitorKeyword(group, keywordIndex)">×</button>
                  </i>
                  <input
                    placeholder="输入后回车添加，支持粘贴多行批量添加"
                    :disabled="!canEditEnterpriseTab('brand_words')"
                    @keyup.enter="commitMonitorKeywordInput(group, $event)"
                    @blur="commitMonitorKeywordInput(group, $event)"
                    @paste="handleMonitorKeywordPaste(group, $event)"
                  />
                </div>
              </div>
              <div v-if="canEditModels" class="keyword-field keyword-group-platform-field">
                <span class="keyword-field-label">监测平台（{{ platformSelectionCount(group) }}）</span>
                <div v-if="!editableCatalogPlatforms.length" class="mini-empty compact-empty">当前职位未配置可勾选平台</div>
                <div v-else class="platform-check-grid compact">
                  <label
                    v-for="platform in editableCatalogPlatforms"
                    :key="`bw-${index}-${platform.code}`"
                    class="platform-check"
                    :class="{
                      'is-disabled': 'selectable' in platform && !platform.selectable && !groupHasPlatform(group, platform.code),
                      'is-unavailable': 'labels' in platform && (platform.labels || []).includes('无服务'),
                      'is-delisted': 'labels' in platform && (platform.labels || []).includes('已下架'),
                    }"
                    @click.prevent="onPlatformCheckClick(index, platform.code, 'brand_words')"
                  >
                    <input
                      type="checkbox"
                      tabindex="-1"
                      :checked="groupHasPlatform(group, platform.code)"
                      :disabled="!canEditModels || !canEditEnterpriseTab('brand_words') || ('selectable' in platform && !platform.selectable && !groupHasPlatform(group, platform.code))"
                    />
                    <PlatformBadge
                      :code="platform.code"
                      size="sm"
                      :label="'name' in platform && platform.name ? platform.name : undefined"
                    />
                    <small
                      v-if="groupHasPlatform(group, platform.code)"
                      class="platform-mode-tag"
                      :title="'点击整块可修改模式'"
                    >
                      {{ platformModeLabel(group, platform.code) }}
                    </small>
                    <small v-if="'labels' in platform && platform.labels?.length" class="platform-status-tag">{{ platform.labels.join('·') }}</small>
                    <button
                      v-if="canEditModels && canEditEnterpriseTab('brand_words') && groupHasPlatform(group, platform.code)"
                      type="button"
                      class="platform-uncheck-btn"
                      title="取消勾选"
                      @click.stop.prevent="removeGroupPlatform(index, platform.code, 'brand_words')"
                    >
                      ×
                    </button>
                  </label>
                </div>
              </div>
            </div>
          </div>
          <div v-if="!brandWordGroupRows.length" class="mini-empty">暂无品牌词组，请先新增一个。</div>
        </div>
        <div class="section-save-actions keyword-save-actions">
          <button
            v-if="!creatingDraftTenant && canEditEnterpriseTab('brand_words')"
            class="filter-search-btn"
            :disabled="loadingBrand || !brandAsset"
            @click="submitBrandWordGroups('品牌词配置已保存')"
          >保存品牌词配置</button>
          <p v-if="!brandAsset && !creatingDraftTenant" class="mini-empty compact-empty">请先保存企业资料，再配置品牌词</p>
        </div>
      </section>
      <section v-if="enterpriseDetailTab === 'schedule'" class="schedule-box">
        <div class="panel-head">
          <div><h2>自动监测计划</h2><p>每天在下方配置的时间点自动提交检测任务。</p></div>
          <button v-if="!creatingDraftTenant && canEditEnterpriseTab('schedule')" class="filter-search-btn" :disabled="loadingBrand || !canSubmitBrandAssetProfile" @click="submitBrandAsset('监测计划已保存')">保存监测计划</button>
        </div>
        <div class="brand-form-grid">
          <div class="schedule-time-picker">
            <div class="schedule-time-title">
              <span>每日执行时间</span>
              <button v-if="canEditEnterpriseTab('schedule')" class="filter-reset-btn" @click="addScheduleTime">新增时间</button>
            </div>
            <div class="schedule-time-list">
              <div v-for="(_, index) in brandForm.schedule_times" :key="`schedule-time-${index}`">
                <input v-model="brandForm.schedule_times[index]" type="time" step="300" :disabled="!canEditEnterpriseTab('schedule')" />
                <button v-if="canEditEnterpriseTab('schedule')" class="danger-text-btn" @click="removeScheduleTime(index)">删除</button>
              </div>
            </div>
            <div v-if="!brandForm.schedule_times.length" class="mini-empty compact-empty">暂无执行时间，请点击「新增时间」配置。</div>
          </div>
        </div>
      </section>
    </article>

    <section v-if="(customerConfigEmbed || enterpriseDetailMode) && ['competitors', 'files', 'credit'].includes(enterpriseDetailTab)" class="brand-layout">
      <article v-if="enterpriseDetailTab === 'competitors'" class="panel competitor-panel">
        <div class="panel-head">
          <div><h2>竞品监控库</h2><p>只维护竞品名称，系统提交任务时自动带入竞品用于排名、提及率和对比分析。</p></div>
        </div>
        <div class="competitor-tag-editor">
          <div class="competitor-add-row">
            <input v-model="competitorNameInput" :disabled="!canEditEnterpriseTab('competitors')" placeholder="输入竞品名称，例如 新榜" @keyup.enter="addCompetitorTag" />
            <button v-if="canEditEnterpriseTab('competitors')" class="filter-search-btn" @click="addCompetitorTag">新增竞品</button>
          </div>
          <div class="competitor-tags">
            <span v-for="(row, index) in competitorRows" :key="row.id || `new-${index}`">
              {{ row.name || '未命名竞品' }}
              <button v-if="canEditEnterpriseTab('competitors')" @click="removeCompetitorRow(row, index)">×</button>
            </span>
          </div>
          <div v-if="!competitorRows.length" class="mini-empty">还没有竞品。建议先录入 3-5 个核心竞品，方便后续自动对比。</div>
        </div>
      </article>
      <article v-if="enterpriseDetailTab === 'files'" class="panel competitor-panel">
        <div class="panel-head">
          <div><h2>企业知识库</h2><p>与客户端同一资料库；可上传、预览、下载或删除资料文件。</p></div>
          <div class="knowledge-panel-actions">
            <span>{{ knowledgeFiles.length }} 个文件</span>
            <button
              v-if="canUploadKnowledgeFiles"
              type="button"
              class="filter-search-btn tiny-btn"
              :disabled="uploadingKnowledgeFile || loadingKnowledgeFiles"
              @click="brandForm.tenant_id && pickKnowledgeUpload(brandForm.tenant_id)"
            >
              {{ uploadingKnowledgeFile ? '上传中…' : '上传' }}
            </button>
          </div>
        </div>
        <div class="knowledge-files">
          <div v-if="loadingKnowledgeFiles" class="mini-empty">文件列表加载中...</div>
          <div v-for="file in knowledgeFiles" :key="file.id" class="knowledge-file-row">
            <div class="knowledge-file-main">
              <b>{{ file.original_name }}</b>
              <span>{{ file.file_ext.toUpperCase() }} · {{ formatFileSize(file.file_size) }} · 已上传</span>
            </div>
            <div class="knowledge-file-actions">
              <button type="button" class="filter-reset-btn tiny-btn" @click="previewKnowledgeFile(file)">预览</button>
              <button type="button" class="filter-reset-btn tiny-btn" @click="downloadKnowledgeFileItem(file)">下载</button>
              <button
                v-if="canDeleteKnowledgeFiles"
                type="button"
                class="danger-text-btn"
                :disabled="loadingKnowledgeFiles"
                @click="removeKnowledgeFile(file)"
              >
                删除
              </button>
            </div>
          </div>
          <div v-if="!loadingKnowledgeFiles && !knowledgeFiles.length" class="mini-empty">该企业暂未上传资料。</div>
        </div>
      </article>
      <TenantCreditPanel
        v-if="enterpriseDetailTab === 'credit' && brandForm.tenant_id"
        :tenant-id="brandForm.tenant_id"
        :can-edit="canEditEnterpriseTab('credit')"
        @billing-mode-changed="loadEnterpriseList"
      />
    </section>

    <input
      ref="knowledgeUploadInputRef"
      type="file"
      class="knowledge-hidden-file-input"
      accept=".pdf,.doc,.docx,.ppt,.pptx,.png,.jpg,.jpeg,.webp,.html,.htm,.md,.txt"
      :disabled="uploadingKnowledgeFile"
      @change="onKnowledgeUploadInput"
    />

    <el-dialog
      v-model="knowledgeUploadDialogVisible"
      width="480px"
      :title="knowledgeUploadTenant ? `上传资料 · ${knowledgeUploadTenant.name}` : '上传资料'"
      destroy-on-close
      @closed="onKnowledgeUploadDialogClosed"
    >
      <p class="knowledge-upload-tip">支持 PDF、Word、Markdown、TXT；单文件不超过 30MB。上传后客户在企业知识库可见。</p>
      <button
        type="button"
        class="primary-btn"
        :disabled="uploadingKnowledgeFile || !knowledgeUploadTenant"
        @click="knowledgeUploadTenant && pickKnowledgeUpload(knowledgeUploadTenant.id)"
      >
        {{ uploadingKnowledgeFile ? '上传中…' : '选择文件并上传' }}
      </button>
      <template #footer>
        <button type="button" class="plain-btn" @click="knowledgeUploadDialogVisible = false">关闭</button>
        <button
          v-if="knowledgeUploadTenant && canViewEnterpriseTab('files')"
          type="button"
          class="filter-reset-btn"
          @click="knowledgeUploadTenant && openEnterpriseDetailFiles(knowledgeUploadTenant)"
        >
          查看文件列表
        </button>
      </template>
    </el-dialog>

    <el-dialog v-model="enterpriseInfoDialog" width="720px" title="企业详情">
      <div v-if="enterpriseInfoLoading" class="mini-empty">企业详情加载中...</div>
      <div v-else class="enterprise-info-dialog">
        <section>
          <h3>{{ enterpriseInfoTenant?.name }}</h3>
          <p>{{ enterpriseInfoTenant ? tenantServicePeriod(enterpriseInfoTenant) : '-' }}</p>
          <div class="info-grid">
            <span><small>服务状态</small><b>{{ enterpriseInfoTenant ? tenantServiceLabel(enterpriseInfoTenant) : '-' }}</b></span>
            <span><small>企业类型</small><b>{{ enterpriseInfoTenant ? tenantBillingLabel(enterpriseInfoTenant) : '-' }}</b></span>
            <span><small>归属销售</small><b>{{ enterpriseInfoTenant ? tenantOwnerLabel(enterpriseInfoTenant) : '-' }}</b></span>
            <span><small>官网</small><b>{{ enterpriseInfoAsset?.official_url || '-' }}</b></span>
            <span><small>购买模型</small><b>{{ formatPlatformLabels(enterpriseInfoAsset?.monitored_platforms || [], platformLabelMap) || '-' }}</b></span>
          </div>
        </section>
        <section>
          <h4>监测关键词</h4>
          <div class="info-tags"><span v-for="item in enterpriseInfoMonitorKeywords" :key="item">{{ item }}</span><em v-if="!enterpriseInfoMonitorKeywords.length">未配置</em></div>
        </section>
        <section>
          <h4>露出词</h4>
          <div class="info-tags"><span v-for="item in enterpriseInfoExposureTerms" :key="item">{{ item }}</span><em v-if="!enterpriseInfoExposureTerms.length">未配置</em></div>
        </section>
        <section>
          <h4>竞品监控</h4>
          <div class="info-tags"><span v-for="item in enterpriseInfoCompetitors" :key="item.id">{{ item.name }}</span><em v-if="!enterpriseInfoCompetitors.length">未配置</em></div>
        </section>
      </div>
      <template #footer>
        <button class="plain-btn" @click="enterpriseInfoDialog = false">关闭</button>
        <button v-if="enterpriseInfoTenant" class="primary-btn" @click="enterpriseInfoDialog = false; openEnterpriseDetail(enterpriseInfoTenant)">进入编辑</button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="knowledgePreviewVisible"
      width="900px"
      :title="knowledgePreviewFile?.original_name || '文件预览'"
      @closed="closeKnowledgePreview"
    >
      <div v-if="knowledgePreviewLoading" class="mini-empty">正在生成原版预览...</div>
      <div v-else-if="knowledgePreviewError" class="mini-empty">{{ knowledgePreviewError }}</div>
      <iframe
        v-else-if="knowledgePreviewUrl"
        class="knowledge-preview-frame"
        :src="knowledgePreviewUrl"
        title="知识库文件原版预览"
      />
      <div v-else class="mini-empty">暂无可预览内容，可尝试下载原文件查看。</div>
      <template #footer>
        <button class="plain-btn" @click="closeKnowledgePreview">关闭</button>
        <button
          v-if="knowledgePreviewFile"
          class="filter-reset-btn"
          @click="downloadKnowledgeFileItem(knowledgePreviewFile)"
        >
          下载原文件
        </button>
      </template>
    </el-dialog>

    <el-dialog v-model="periodExportDialog" width="520px" title="导出报告">
      <p v-if="periodExportTenant" class="report-dialog-hint">
        为「{{ periodExportTenant.name }}」导出 {{ periodExportHint }}。已有监测数据会写入报告，未完成的日期不补。
      </p>
      <div class="form-grid password-grid">
        <label class="form-field-full">
          <span>报告类型</span>
          <select v-model="periodExportKind" :disabled="periodExporting">
            <option v-for="item in periodExportKinds" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label>
          <span>开始日期</span>
          <input v-model="periodExportStart" type="date" :disabled="periodExporting" />
        </label>
        <label>
          <span>结束日期</span>
          <input v-model="periodExportEnd" type="date" :disabled="periodExporting" />
        </label>
      </div>
      <template #footer>
        <button class="plain-btn" :disabled="periodExporting" @click="periodExportDialog = false">取消</button>
        <button class="primary-btn" :disabled="periodExporting" @click="submitPeriodExport">
          {{ periodExporting ? (periodExportProgress || '导出中…') : '导出' }}
        </button>
      </template>
    </el-dialog>

    <el-dialog v-model="reportDialog" width="520px" title="生成品牌诊断报告">
      <p v-if="reportDialogTenant" class="report-dialog-hint">
        为「{{ reportDialogTenant.name }}」生成企业内部品牌诊断，仅供运营预览与导出，不会出现在客户端报告中心。
        周报/月报/季报/年报由系统按周期自动生成并发布至客户端。
      </p>
      <div class="form-grid password-grid">
        <label class="form-field-full">
          <span>报告标题（可选）</span>
          <input v-model="reportTitle" placeholder="留空则使用默认标题「GEO 企业诊断报告」" />
        </label>
      </div>
      <template #footer>
        <button class="plain-btn" @click="reportDialog = false">取消</button>
        <button class="primary-btn" :disabled="reportGenerating" @click="submitEnterpriseReport">
          {{ reportGenerating ? '生成中…' : '生成报告' }}
        </button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="modeDialogVisible"
      width="440px"
      title="选择监测模式"
      destroy-on-close
      append-to-body
      @closed="cancelModeDialog"
    >
      <div class="form-grid password-grid">
        <label class="form-field-full">
          <span>模式</span>
          <select v-model="modeDialogForm.mode">
            <option value="standard">快速</option>
            <option value="reasoning">深度思考</option>
          </select>
        </label>
      </div>
      <template #footer>
        <button type="button" class="plain-btn" @click="cancelModeDialog">取消</button>
        <button type="button" class="primary-btn" @click="confirmModeDialog">确认</button>
      </template>
    </el-dialog>

    <el-dialog v-model="tenantTransferDialog" width="520px" title="转移归属销售">
      <p v-if="tenantTransferTarget" class="report-dialog-hint">
        将「{{ tenantTransferTarget.name }}」的归属销售从「{{ tenantOwnerLabel(tenantTransferTarget) }}」转移给其他销售账号。转移后原销售将无法访问该企业。
      </p>
      <div class="form-grid password-grid">
        <label class="form-field-full">
          <span>目标销售</span>
          <select v-model.number="tenantTransferOwnerId" :disabled="loadingTenantSalesOwners || transferringTenantOwner">
            <option disabled :value="null">{{ loadingTenantSalesOwners ? '销售列表加载中…' : '请选择销售账号' }}</option>
            <option v-for="owner in tenantSalesOwners" :key="owner.id" :value="owner.id">
              {{ owner.display_name }}（{{ owner.username }}）
            </option>
          </select>
        </label>
      </div>
      <template #footer>
        <button class="plain-btn" @click="tenantTransferDialog = false">取消</button>
        <button class="primary-btn" :disabled="loadingTenantSalesOwners || transferringTenantOwner" @click="submitTenantTransfer">
          {{ transferringTenantOwner ? '提交中…' : '确认转移' }}
        </button>
      </template>
    </el-dialog>

    <el-dialog v-model="tenantDialog" width="520px" title="新增企业">
      <div class="form-grid password-grid">
        <label><span>企业名称</span><input v-model="tenantForm.name" placeholder="例如 北京某某科技有限公司" /></label>
        <label><span>服务开始日期</span><input v-model="tenantForm.service_start_date" type="date" /></label>
        <label><span>服务结束日期</span><input v-model="tenantForm.service_end_date" type="date" /></label>
        <label class="form-field-full">
          <span>企业类型</span>
          <select v-model="tenantForm.billing_mode">
            <option value="hosted">平台托管</option>
            <option value="credit">算力自助</option>
          </select>
        </label>
        <label class="form-field-full">
          <span>企业 Logo（选填）</span>
          <TenantLogoField
            :preview-src="pendingTenantLogoPreview || undefined"
            :file-name="pendingTenantLogoFileName"
            @pick="onTenantLogoPick"
            @clear="clearPendingTenantLogo"
          />
        </label>
      </div>
      <template #footer>
        <button class="plain-btn" @click="tenantDialog = false; clearPendingTenantLogo()">取消</button>
        <button class="primary-btn" :disabled="loadingBrand" @click="goNextFromTenantDialog">下一步</button>
      </template>
    </el-dialog>
  </section>
</template>
