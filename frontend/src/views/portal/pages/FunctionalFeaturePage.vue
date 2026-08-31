<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { useAuthStore } from '../../../stores/auth'
import { usePortalCharts } from '../../../composables/usePortalCharts'
import { withRetry } from '../../../composables/useRetry'
import {
  getManagementPositions,
  getTenants,
  updateSystemConfig,
  type PositionInfo,
  type TenantInfo,
} from '../../../services/management'
import { getOperationLogs, type OperationLogRecord } from '../../../services/ops'
import {
  previewScheduledMonitor,
  runDueScheduledMonitor,
  type ScheduledMonitorPreview,
} from '../../../services/monitor'
import { PortalAnalyticsKey, PortalNavigateKey } from '../injectionKeys'
import { monitorStatusLabelMap, platformLabelMap } from '../portalMaps'
import { externalLink } from '../portalUtils'
import {
  SETTINGS_CACHE_QUEUE_MENU,
  SETTINGS_CHILD_MENUS,
  SETTINGS_MENU,
  SETTINGS_MENU_PERM,
  SETTINGS_NOTIFICATION_MENU,
  SETTINGS_SCHEDULE_MENU,
  SETTINGS_SECRETS_MENU,
} from '../constants'
import PlatformMatrixPanel from '../components/PlatformMatrixPanel.vue'
import H5DiagnosisConfigPanel from '../components/H5DiagnosisConfigPanel.vue'
import '../../../styles/platform-matrix.css'

const emit = defineEmits<{ 'open-menu-config': [] }>()

const auth = useAuthStore()
const isPlatformView = computed(() => auth.session?.identity?.identity_type === 'PLATFORM')
const portalNavigate = inject(PortalNavigateKey)!

const analytics = inject(PortalAnalyticsKey)!
const {
  monitorSummary,
  brandAsset,
  brandCompetitors,
  functionalPage,
  negativeRate,
  sourceTotalCount,
  sourceRanking,
  diagnosisScore,
  platformCoverage,
  platformMatrix,
  loadingPlatformMatrix,
  loadPlatformMatrix,
  platformRanking,
  systemConfigRows,
  loadPlatformSystemData,
  recentSubtasks,
} = analytics

type SettingsCategory = 'secrets' | 'schedule' | 'cache_queue' | 'notification' | 'menu'

const SETTINGS_MENU_BY_CATEGORY: Record<SettingsCategory, string> = {
  secrets: SETTINGS_SECRETS_MENU,
  schedule: SETTINGS_SCHEDULE_MENU,
  cache_queue: SETTINGS_CACHE_QUEUE_MENU,
  notification: SETTINGS_NOTIFICATION_MENU,
  menu: SETTINGS_MENU_PERM,
}

function menuHasAccess(menuCode: string) {
  return auth.allowedMenus.some(menu => (
    menu.menu_code === menuCode && Boolean(menu.can_export || menu.can_update)
  ))
}

function canAccessSettingsCategory(key: SettingsCategory) {
  const childCode = SETTINGS_MENU_BY_CATEGORY[key]
  if (menuHasAccess(childCode)) return true
  // 有任意配置子权限时，仅按子项授权；无子项时兼容旧的父菜单整页授权
  const hasAnyChild = SETTINGS_CHILD_MENUS.some(code => menuHasAccess(code))
  if (hasAnyChild) return false
  return menuHasAccess(SETTINGS_MENU)
}

const settingsCategory = ref<SettingsCategory>('secrets')

const settingsTabs = computed(() => {
  const all: Array<{ key: SettingsCategory; title: string; desc: string }> = [
    { key: 'secrets', title: '接口密钥', desc: '监测服务、DeepSeek 等敏感配置，保存后立即生效' },
    { key: 'schedule', title: '调度策略', desc: 'H5 付费诊断、监测容差、接口限速与 Celery 参数' },
    { key: 'cache_queue', title: '缓存与队列', desc: 'Redis / Celery 连接与队列预警阈值' },
    { key: 'notification', title: '通知规则', desc: '补录谁收、客户即将到期天数/职位、弱排名阈值' },
    { key: 'menu', title: '菜单权限', desc: '平台端与客户端菜单可见性配置' },
  ]
  return all.filter(tab => canAccessSettingsCategory(tab.key))
})

watch(settingsTabs, (tabs) => {
  if (!tabs.length) return
  if (!tabs.some(tab => tab.key === settingsCategory.value)) {
    settingsCategory.value = tabs[0].key
  }
}, { immediate: true })

const filteredConfigRows = computed(() => {
  if (settingsCategory.value === 'menu') return []
  const rows = systemConfigRows.value.filter(row => (row.category || row.scope) === settingsCategory.value)
  if (settingsCategory.value === 'schedule') {
    return rows.filter(row => !String(row.config_key || '').startsWith('h5_diagnosis_'))
  }
  return rows
})

const canEditScheduleSettings = computed(() => canAccessSettingsCategory('schedule'))

function switchSettingsCategory(key: SettingsCategory) {
  if (!canAccessSettingsCategory(key)) return
  settingsCategory.value = key
  cancelEditConfig()
}

const primaryPanelTitle = computed(() => {
  const mode = functionalPage.value.mode
  if (mode === 'diagnosis') return '品牌健康分'
  if (mode === 'report') return '报告预览'
  if (mode === 'platforms') return ''
  if (mode === 'logs' || mode === 'settings') return ''
  return '检测明细'
})

const showFeatureHero = computed(() => {
  const mode = functionalPage.value.mode
  return mode !== 'logs' && mode !== 'settings' && mode !== 'platforms'
})

const editingConfigId = ref<number | null>(null)
const editingConfigValue = ref('')
const savingConfig = ref(false)

const logFilterPanelRef = ref<HTMLElement | null>(null)
const logDays = ref(7)
const logActionType = ref('')
const logKeyword = ref('')
const logTenantId = ref<number | ''>('')
const logLoading = ref(false)
const logRows = ref<OperationLogRecord[]>([])
const logTotal = ref(0)
const logPage = ref(1)
const logPageSize = ref(20)
const logTenants = ref<TenantInfo[]>([])

const schedulePreview = ref<ScheduledMonitorPreview[]>([])
const schedulePreviewLoading = ref(false)
const scheduleRunLoading = ref(false)
const scheduleTenantId = ref<number | ''>('')
const platformPositions = ref<PositionInfo[]>([])
const editingPositionIds = ref<number[]>([])

function isSecretConfigRow(row: { config_key: string; secret?: boolean }) {
  return row.secret || isSecretConfigKey(row.config_key)
}

function isPositionNotifyConfig(row: { config_key: string }) {
  return (
    row.config_key === 'platform_service_notify_position_ids'
    || row.config_key === 'tenant_expiry_notify_position_ids'
  )
}

function isTenantExpiryPositionConfig(row: { config_key: string }) {
  return row.config_key === 'tenant_expiry_notify_position_ids'
}

function configValuePlaceholder(row: { value_type?: string }) {
  if (row.value_type === 'bool') return '请选择是或否'
  if (row.value_type === 'int' || row.value_type === 'float') return '请输入数字'
  return '请输入配置值'
}

function isSecretConfigKey(key: string) {
  return /(?:^|_)(?:api_key|token|secret|password)(?:_|$)/i.test(key) || /(?:^|_)token$/i.test(key)
}

function isTruthyConfig(value: string) {
  return ['1', 'true', 'yes', 'on', '启用', '是'].includes(String(value || '').trim().toLowerCase())
}

function formatBoolDisplay(value: string) {
  const text = String(value || '').trim()
  if (!text) return '-'
  if (isTruthyConfig(text)) return '是'
  if (['0', 'false', 'no', 'off', '停用', '否'].includes(text.toLowerCase())) return '否'
  return text
}

function parsePositionIds(raw: string): number[] {
  try {
    const parsed = JSON.parse(raw || '[]') as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.map(Number).filter((id) => Number.isFinite(id) && id > 0)
  } catch {
    return []
  }
}

function formatPositionIdsDisplay(raw: string, configKey?: string) {
  const ids = parsePositionIds(raw)
  if (!ids.length) {
    return configKey === 'tenant_expiry_notify_position_ids'
      ? '未选择（不推送）'
      : '默认（销售+运营+管理员）'
  }
  return ids
    .map((id) => platformPositions.value.find((item) => item.id === id)?.position_name || `#${id}`)
    .join('、')
}

function formatConfigDisplay(row: {
  config_key: string
  config_value: string
  value_type?: string
  secret?: boolean
}) {
  if (row.value_type === 'bool') return formatBoolDisplay(row.config_value)
  if (isPositionNotifyConfig(row)) return formatPositionIdsDisplay(row.config_value, row.config_key)
  return maskedConfigValue(row.config_value, row.config_key, row.secret)
}

function maskedConfigValue(value: string, key: string, secret?: boolean) {
  if (!value) return '-'
  if (!secret && !isSecretConfigKey(key)) return value
  if (value.length <= 8) return '****'
  return `${value.slice(0, 4)}****${value.slice(-4)}`
}

function schedulePreviewTitle(item: ScheduledMonitorPreview) {
  const tenant = String(item.tenant_name || '').trim()
  const brand = String(item.brand_name || '').trim()
  if (tenant && brand && tenant !== brand) return `${tenant} · ${brand}`
  return tenant || brand || `企业 #${item.tenant_id}`
}

async function ensurePlatformPositions() {
  if (platformPositions.value.length) return
  try {
    platformPositions.value = await withRetry(() => getManagementPositions('PLATFORM'))
  } catch {
    platformPositions.value = []
  }
}

function startEditConfig(row: {
  id: number
  config_key: string
  config_value: string
  value_type?: string
}) {
  editingConfigId.value = row.id
  if (row.value_type === 'bool') {
    editingConfigValue.value = isTruthyConfig(row.config_value) ? 'true' : 'false'
    editingPositionIds.value = []
    return
  }
  if (isPositionNotifyConfig(row)) {
    editingPositionIds.value = parsePositionIds(row.config_value)
    editingConfigValue.value = JSON.stringify(editingPositionIds.value)
    void ensurePlatformPositions()
    return
  }
  editingPositionIds.value = []
  editingConfigValue.value = row.config_value
}

function cancelEditConfig() {
  editingConfigId.value = null
  editingConfigValue.value = ''
  editingPositionIds.value = []
}

async function saveConfigRow(row: {
  id: number
  config_key: string
  category?: string
  scope?: string
  value_type?: string
}) {
  const nextValue = isPositionNotifyConfig(row)
    ? JSON.stringify(editingPositionIds.value)
    : editingConfigValue.value.trim()
  if (!isPositionNotifyConfig(row) && !nextValue) {
    ElMessage.warning('配置值不能为空')
    return
  }
  savingConfig.value = true
  try {
    await updateSystemConfig(row.id, nextValue)
    ElMessage.success('配置已更新并立即生效')
    if ((row.category || row.scope) === 'cache_queue') {
      ElMessage.info('Redis / Celery 连接变更后，建议重启 Worker 与 API 以确保队列完全生效')
    }
    cancelEditConfig()
    await loadPlatformSystemData()
  } catch (error: unknown) {
    ElMessage.error(error instanceof Error ? error.message : '配置更新失败')
  } finally {
    savingConfig.value = false
  }
}

watch(settingsCategory, (category) => {
  if (category === 'notification') void ensurePlatformPositions()
})

function navigateToMenu(menuCode: string) {
  portalNavigate(menuCode)
}

function formatLogTime(value: string) {
  return value.replace('T', ' ').slice(0, 16)
}

/** 2026-07-31 - 彻底删除日志把备份绝对路径挤进上下文列 - 描述里「备份 …」拆第二行展示 */
function logDescriptionParts(description: string | null | undefined) {
  const text = String(description || '').trim()
  const matched = text.match(/^(.*?)[（(]备份\s*(.+?)[）)]\s*$/u)
  if (!matched) {
    return { summary: text, backup: '' }
  }
  return {
    summary: matched[1].trim(),
    backup: matched[2].trim(),
  }
}

function logContext(row: OperationLogRecord) {
  return [
    row.target_module,
    row.tenant_name || '',
    row.ip_address ? `IP ${row.ip_address}` : '',
  ].filter(Boolean).join(' · ') || '平台操作'
}

const logTotalPages = computed(() => Math.max(1, Math.ceil(logTotal.value / logPageSize.value)))

async function loadOperationLogs(page = logPage.value) {
  if (functionalPage.value.mode !== 'logs') return
  logLoading.value = true
  try {
    const result = await withRetry(() => getOperationLogs({
      days: logDays.value,
      action_type: logActionType.value.trim() || undefined,
      keyword: logKeyword.value.trim() || undefined,
      tenant_id: logTenantId.value === '' ? undefined : Number(logTenantId.value),
      page,
      page_size: logPageSize.value,
    }))
    logRows.value = result.items
    logTotal.value = result.total
    logPage.value = result.page
  } catch (error: unknown) {
    ElMessage.error(error instanceof Error ? error.message : '操作日志加载失败')
  } finally {
    logLoading.value = false
  }
}

function changeLogPage(page: number) {
  if (page < 1 || page > logTotalPages.value || page === logPage.value) return
  void loadOperationLogs(page)
}

function handleLogPageSizeChange() {
  logPage.value = 1
  void loadOperationLogs(1)
}

function searchOperationLogs() {
  logPage.value = 1
  void loadOperationLogs(1)
}

function resetLogFilters() {
  logDays.value = 7
  logActionType.value = ''
  logKeyword.value = ''
  logTenantId.value = ''
  logPage.value = 1
  void loadOperationLogs(1)
}

async function exportLogsCsv() {
  logLoading.value = true
  try {
    const rows: OperationLogRecord[] = []
    const pageSize = 100
    let page = 1
    let total = 0
    do {
      const result = await getOperationLogs({
        days: logDays.value,
        action_type: logActionType.value.trim() || undefined,
        keyword: logKeyword.value.trim() || undefined,
        tenant_id: logTenantId.value === '' ? undefined : Number(logTenantId.value),
        page,
        page_size: pageSize,
      })
      rows.push(...result.items)
      total = result.total
      page += 1
    } while (rows.length < total)

    if (!rows.length) {
      ElMessage.warning('当前筛选结果为空，无法导出')
      return
    }
    const header = ['时间', '操作人', '类型', '描述', '模块', '企业', 'IP', '风险']
    const lines = rows.map(row => [
      formatLogTime(row.created_at),
      row.operator_name,
      row.action_type,
      row.description,
      row.target_module || '',
      row.tenant_name || '',
      row.ip_address || '',
      row.risk_level,
    ].map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    const blob = new Blob([`\uFEFF${[header.join(','), ...lines].join('\n')}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `operation-logs-${new Date().toISOString().slice(0, 10)}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${rows.length} 条日志`)
  } catch (error: unknown) {
    ElMessage.error(error instanceof Error ? error.message : '日志导出失败')
  } finally {
    logLoading.value = false
  }
}

function exportConfigsCsv() {
  const rows = systemConfigRows.value
  if (!rows.length) {
    ElMessage.warning('暂无配置可导出')
    return
  }
  const header = ['配置项', '键名', '当前值', '说明', '状态']
  const lines = rows.map(row => [
    row.config_name || row.config_key,
    row.config_key,
    maskedConfigValue(row.config_value, row.config_key, row.secret),
    row.remark || row.scope || '平台运行配置',
    row.status || '启用',
  ].map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
  const blob = new Blob([`\uFEFF${[header.join(','), ...lines].join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `system-configs-${new Date().toISOString().slice(0, 10)}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出 ${rows.length} 项配置`)
}

function focusLogFilters() {
  logFilterPanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function loadSchedulePreview() {
  schedulePreviewLoading.value = true
  try {
    schedulePreview.value = await withRetry(() => previewScheduledMonitor(
      scheduleTenantId.value === '' ? null : Number(scheduleTenantId.value),
    ))
  } catch (error: unknown) {
    ElMessage.error(error instanceof Error ? error.message : '调度预览失败')
  } finally {
    schedulePreviewLoading.value = false
  }
}

async function runDueSchedule() {
  scheduleRunLoading.value = true
  try {
    const result = await runDueScheduledMonitor({
      tenant_id: scheduleTenantId.value === '' ? undefined : Number(scheduleTenantId.value),
      force: true,
      limit: 10,
    })
    ElMessage.success(`已触发 ${result.length} 个到期调度`)
    await loadSchedulePreview()
  } catch (error: unknown) {
    ElMessage.error(error instanceof Error ? error.message : '调度执行失败')
  } finally {
    scheduleRunLoading.value = false
  }
}

function handleAction(action: string) {
  const mode = functionalPage.value.mode
  if (action === '导出日志') {
    exportLogsCsv()
    return
  }
  if (action === '筛选操作') {
    focusLogFilters()
    return
  }
  if (action === '刷新状态' || action === '刷新数据') {
    void loadPlatformMatrix(true)
    return
  }
  if (action === '刷新配置' || action === '刷新日志') {
    if (mode === 'logs') void loadOperationLogs()
    else void loadPlatformSystemData()
    return
  }
  if (action === '导出配置') {
    exportConfigsCsv()
    return
  }
  if (action === '操作日志') {
    navigateToMenu('platform.logs')
    return
  }
  if (action.includes('菜单')) {
    emit('open-menu-config')
    return
  }
  if (action.includes('刷新监控') || action === '查看规则') {
    navigateToMenu('platform.alerts')
    return
  }
  if (action.includes('快照') || action.includes('实时') || action.includes('历史任务')) {
    navigateToMenu(isPlatformView.value ? 'platform.audit' : 'customer.realtime')
    return
  }
  if (action.includes('信源')) {
    navigateToMenu(isPlatformView.value ? 'platform.sources' : 'customer.sources')
    return
  }
  if (action.includes('竞品') || action.includes('对比') || action.includes('洞察')) {
    navigateToMenu(isPlatformView.value ? 'platform.competitor' : 'customer.competitor')
    return
  }
  if (action.includes('报告') || action.includes('PDF') || action.includes('Word')) {
    navigateToMenu(isPlatformView.value ? 'platform.reports' : 'customer.reports')
    return
  }
  if (action.includes('知识') || action.includes('上传资料')) {
    navigateToMenu('customer.knowledge')
    return
  }
  if (action === '保存诊断' || action.includes('诊断报告')) {
    navigateToMenu('platform.lead_diagnosis')
    return
  }
  if (action.includes('补录') || action.includes('提交')) {
    navigateToMenu('platform.snapshot_backfill')
    return
  }
  ElMessage.info(`「${action}」请通过左侧菜单进入对应功能页`)
}

const diagnosisChartRef = ref<HTMLDivElement | null>(null)

const { renderCharts } = usePortalCharts({
  diagnosis: diagnosisChartRef,
})

const chartData = computed(() => ({
  chartTrend: [],
  platformRanking: platformRanking.value,
  sentimentPieRows: [],
  positiveRate: 0,
  diagnosisScore: diagnosisScore.value,
  competitorCompareRows: [],
  sourceStructureRows: [],
  sourceTrendRows: [],
  sourceCategoryLabels: {},
}))

async function refreshCharts() {
  await renderCharts(chartData.value)
}

watch([
  platformRanking,
  diagnosisScore,
], refreshCharts, { deep: true })

watch(() => functionalPage.value.mode, async (mode) => {
  if (mode === 'logs' || mode === 'settings') {
    if (!logTenants.value.length) {
      try {
        logTenants.value = await withRetry(() => getTenants())
      } catch {
        logTenants.value = []
      }
    }
  }
  if (mode === 'logs') {
    await loadOperationLogs()
  }
  if (mode === 'settings' && settingsCategory.value === 'schedule') {
    await loadSchedulePreview()
  }
}, { immediate: true })

watch(settingsCategory, (category) => {
  if (category === 'schedule' && functionalPage.value.mode === 'settings') {
    void loadSchedulePreview()
  }
})

onMounted(() => {
  refreshCharts()
  window.addEventListener('resize', refreshCharts)
})

onUnmounted(() => {
  window.removeEventListener('resize', refreshCharts)
})
</script>

<template>
  <section class="feature-page">
    <article v-if="showFeatureHero" class="panel feature-hero">
      <div>
        <small>{{ functionalPage.subtitle }}</small>
        <h2>{{ functionalPage.title }}</h2>
        <div class="feature-kpi-row">
          <span v-for="kpi in functionalPage.kpis" :key="kpi.label">
            <b>{{ kpi.value }}</b>{{ kpi.label }}<em>{{ kpi.note }}</em>
          </span>
        </div>
      </div>
      <div v-if="functionalPage.actions.length" class="feature-actions">
        <button
          v-for="action in functionalPage.actions"
          :key="action"
          type="button"
          class="ghost-link-btn"
          @click="handleAction(action)"
        >
          {{ action }}
        </button>
      </div>
    </article>

    <section class="feature-grid">
      <article class="panel feature-primary">
        <div v-if="primaryPanelTitle" class="panel-head">
          <h2>{{ primaryPanelTitle }}</h2>
        </div>

        <div v-if="functionalPage.mode === 'diagnosis'" class="diagnosis-workbench">
          <div v-if="diagnosisScore" ref="diagnosisChartRef" class="echart-box diagnosis-echart"></div>
          <div v-else class="mini-empty chart-empty">暂无可诊断的真实结果。</div>
          <div class="diagnosis-bars">
            <div><span>品牌提及率</span><i><b :style="{ width: `${monitorSummary?.mention_rate || 0}%` }"></b></i><em>{{ monitorSummary?.mention_rate || 0 }}%</em></div>
            <div><span>平均排名</span><i><b :style="{ width: `${monitorSummary?.avg_rank ? Math.max(12, 100 - monitorSummary.avg_rank * 12) : 0}%` }"></b></i><em>{{ monitorSummary?.avg_rank || '-' }}</em></div>
            <div><span>负面风险</span><i><b class="warn-bar" :style="{ width: `${negativeRate}%` }"></b></i><em>{{ negativeRate }}%</em></div>
            <div><span>信源数量</span><i><b :style="{ width: `${Math.min(100, (sourceTotalCount || sourceRanking.length) * 10)}%` }"></b></i><em>{{ sourceTotalCount || sourceRanking.length }}</em></div>
          </div>
          <div class="diagnosis-basis">
            <h3>诊断依据</h3>
            <p>依据已配置监测平台、品牌词、竞品库、模型回答排名、信源数量、情感倾向和历史任务完成情况综合判断。</p>
            <div><span>诊断平台</span><b>{{ platformCoverage.map(item => item.name).join('、') }}</b></div>
            <div><span>纳入竞品</span><b>{{ brandCompetitors.map(item => item.name).join('、') || '暂未配置竞品' }}</b></div>
          </div>
        </div>

        <PlatformMatrixPanel
          v-else-if="functionalPage.mode === 'platforms'"
          :matrix="platformMatrix"
          :loading="loadingPlatformMatrix"
          @refresh="loadPlatformMatrix(true)"
        />

        <div v-else-if="functionalPage.mode === 'report'" class="report-preview">
          <!-- 2026-08-20 - 报告预览标题勿默认艾迪亚 - 无品牌资产时用中性兜底 -->
          <h3>{{ brandAsset?.brand_name || '本品牌' }} GEO 监测诊断报告</h3>
          <p>本周期共完成 {{ monitorSummary?.subtask_count || 0 }} 个检测子任务，品牌提及率 {{ monitorSummary?.mention_rate || 0 }}%，平均推荐排名 {{ monitorSummary?.avg_rank || '-' }}。主要优化方向集中在高权威信源、竞品对比内容和移动端结果稳定性。</p>
          <div class="report-table">
            <span>平台</span><span>提及率</span><span>平均排名</span><span>建议动作</span>
            <template v-for="item in platformRanking.slice(0, 4)" :key="item.platform">
              <b>{{ platformLabelMap[item.platform] || item.platform }}</b><b>{{ item.mention_rate }}%</b><b>{{ item.avg_rank || '-' }}</b><b>补充可引用内容</b>
            </template>
          </div>
        </div>

        <div v-else-if="functionalPage.mode === 'logs'" class="ops-table">
          <div ref="logFilterPanelRef" class="log-filter-bar">
            <select v-model.number="logDays" title="时间范围">
              <option :value="7">近 7 天</option>
              <option :value="30">近 30 天</option>
              <option :value="90">近 90 天</option>
            </select>
            <input v-model="logActionType" type="text" placeholder="操作类型" title="操作类型">
            <input v-model="logKeyword" type="text" placeholder="描述关键词" title="描述关键词">
            <select v-model="logTenantId" title="企业">
              <option value="">全部企业</option>
              <option v-for="tenant in logTenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
            </select>
            <button type="button" class="primary-btn small-btn" :disabled="logLoading" @click="searchOperationLogs">查询</button>
            <button type="button" class="filter-reset-btn tiny-btn" :disabled="logLoading" @click="resetLogFilters">重置</button>
            <button type="button" class="filter-reset-btn tiny-btn" :disabled="logLoading || !logTotal" @click="exportLogsCsv">导出 CSV</button>
          </div>
          <div class="ops-head ops-head-detailed"><span>时间</span><span>操作人</span><span>类型</span><span>描述</span><span>上下文</span><span>风险</span></div>
          <div v-if="logLoading" class="mini-empty">加载中…</div>
          <div v-else-if="!logRows.length" class="mini-empty">当前筛选条件下暂无日志。</div>
          <div v-for="row in logRows" :key="row.id" class="ops-row">
            <span>{{ formatLogTime(row.created_at) }}</span>
            <b>{{ row.operator_name }}</b>
            <span>{{ row.action_type }}</span>
            <template v-for="parts in [logDescriptionParts(row.description)]" :key="`${row.id}-desc`">
              <em class="ops-log-desc">
                <span>{{ parts.summary }}</span>
                <small v-if="parts.backup">备份 {{ parts.backup }}</small>
              </em>
            </template>
            <span>{{ logContext(row) }}</span>
            <i>{{ row.risk_level }}</i>
          </div>
          <div v-if="logTotal > 0" class="log-pagination">
            <span class="log-pagination-meta">共 {{ logTotal }} 条，第 {{ logPage }} / {{ logTotalPages }} 页</span>
            <div class="log-pagination-actions">
              <select v-model.number="logPageSize" :disabled="logLoading" title="每页条数" @change="handleLogPageSizeChange">
                <option :value="20">20 条/页</option>
                <option :value="50">50 条/页</option>
                <option :value="100">100 条/页</option>
              </select>
              <button type="button" class="filter-reset-btn tiny-btn" :disabled="logLoading || logPage <= 1" @click="changeLogPage(logPage - 1)">上一页</button>
              <button type="button" class="filter-reset-btn tiny-btn" :disabled="logLoading || logPage >= logTotalPages" @click="changeLogPage(logPage + 1)">下一页</button>
            </div>
          </div>
        </div>

        <div v-else-if="functionalPage.mode === 'settings'" class="ops-table settings-table">
          <div class="settings-header-actions">
            <button class="primary-btn small-btn" @click="loadPlatformSystemData">刷新配置</button>
          </div>
          <div class="settings-summary-grid">
            <article
              v-for="tab in settingsTabs"
              :key="tab.key"
              :class="{ 'is-active': settingsCategory === tab.key }"
              role="button"
              tabindex="0"
              @click="switchSettingsCategory(tab.key)"
              @keyup.enter="switchSettingsCategory(tab.key)"
            >
              <b>{{ tab.title }}</b>
              <span>{{ tab.desc }}</span>
            </article>
          </div>

          <div v-if="settingsCategory === 'menu'" class="settings-menu-panel">
            <p>菜单权限通过「菜单配置管理」维护，调整后立即作用于平台运营端与客户企业端导航。</p>
            <button class="primary-btn small-btn" @click="emit('open-menu-config')">打开菜单配置管理</button>
          </div>

          <div v-else-if="settingsCategory === 'schedule'" class="schedule-settings-wrap">
            <H5DiagnosisConfigPanel :can-edit="canEditScheduleSettings" />
            <div class="schedule-ops-panel">
            <p>预览各企业定时监测将提交的问题与平台；「立即执行到期调度」会发起真实抓取，请谨慎操作。</p>
            <div class="schedule-ops-toolbar">
              <select v-model="scheduleTenantId" title="企业">
                <option value="">全部企业</option>
                <option v-for="tenant in logTenants" :key="tenant.id" :value="tenant.id">{{ tenant.name }}</option>
              </select>
              <button type="button" class="primary-btn small-btn" :disabled="schedulePreviewLoading" @click="loadSchedulePreview">预览调度</button>
              <button type="button" class="filter-reset-btn tiny-btn" :disabled="scheduleRunLoading" @click="runDueSchedule">立即执行到期调度</button>
            </div>
            <div v-if="schedulePreviewLoading" class="mini-empty">加载预览…</div>
            <div v-else-if="!schedulePreview.length" class="mini-empty">当前无到期或待提交的调度任务。</div>
            <div v-else class="schedule-preview-list">
              <div v-for="(item, index) in schedulePreview.slice(0, 12)" :key="`${item.tenant_id}-${index}`" class="schedule-preview-row">
                <b>{{ schedulePreviewTitle(item) }}</b>
                <span>{{ item.prompt_count }} 个问题 · {{ item.platform_count || 0 }} 个平台</span>
                <em>{{ item.schedule_times?.length ? `每日 ${item.schedule_times.join('、')}` : item.schedule_type }}</em>
              </div>
            </div>
            </div>

            <div class="ops-head"><span>配置项</span><span>当前值</span><span>说明</span><span>状态</span><span>操作</span></div>
            <div v-for="row in filteredConfigRows" :key="row.id" class="ops-row settings-config-row">
              <b>{{ row.config_name || row.config_key }}</b>
              <span v-if="editingConfigId !== row.id">{{ formatConfigDisplay(row) }}</span>
              <select
                v-else-if="row.value_type === 'bool'"
                v-model="editingConfigValue"
                class="settings-config-input"
              >
                <option value="true">是</option>
                <option value="false">否</option>
              </select>
              <ElSelect
                v-else-if="isPositionNotifyConfig(row)"
                v-model="editingPositionIds"
                class="settings-config-select"
                multiple
                filterable
                clearable
                collapse-tags
                collapse-tags-tooltip
                :placeholder="isTenantExpiryPositionConfig(row) ? '不选则不推送' : '不选则默认销售+运营+管理员'"
              >
                <ElOption
                  v-for="position in platformPositions"
                  :key="position.id"
                  :label="position.position_name"
                  :value="position.id"
                />
              </ElSelect>
              <input
                v-else
                v-model="editingConfigValue"
                class="settings-config-input"
                :type="isSecretConfigRow(row) ? 'password' : 'text'"
                :placeholder="configValuePlaceholder(row)"
              >
              <em>{{ row.remark || '平台运行配置' }}</em>
              <i>{{ row.status || '启用' }}</i>
              <span class="settings-config-actions">
                <button
                  v-if="editingConfigId !== row.id"
                  type="button"
                  class="filter-reset-btn tiny-btn"
                  @click="startEditConfig(row)"
                >
                  编辑
                </button>
                <template v-else>
                  <button type="button" class="primary-btn small-btn" :disabled="savingConfig" @click="saveConfigRow(row)">保存</button>
                  <button type="button" class="filter-reset-btn tiny-btn" @click="cancelEditConfig">取消</button>
                </template>
              </span>
            </div>
            <div v-if="!filteredConfigRows.length" class="mini-empty">该分类暂无其它配置项。</div>
          </div>

          <template v-else>
            <div class="ops-head"><span>配置项</span><span>当前值</span><span>说明</span><span>状态</span><span>操作</span></div>
            <div v-for="row in filteredConfigRows" :key="row.id" class="ops-row settings-config-row">
              <b>{{ row.config_name || row.config_key }}</b>
              <span v-if="editingConfigId !== row.id">{{ formatConfigDisplay(row) }}</span>
              <select
                v-else-if="row.value_type === 'bool'"
                v-model="editingConfigValue"
                class="settings-config-input"
              >
                <option value="true">是</option>
                <option value="false">否</option>
              </select>
              <ElSelect
                v-else-if="isPositionNotifyConfig(row)"
                v-model="editingPositionIds"
                class="settings-config-select"
                multiple
                filterable
                clearable
                collapse-tags
                collapse-tags-tooltip
                :placeholder="isTenantExpiryPositionConfig(row) ? '不选则不推送' : '不选则默认销售+运营+管理员'"
              >
                <ElOption
                  v-for="position in platformPositions"
                  :key="position.id"
                  :label="position.position_name"
                  :value="position.id"
                />
              </ElSelect>
              <input
                v-else
                v-model="editingConfigValue"
                class="settings-config-input"
                :type="isSecretConfigRow(row) ? 'password' : 'text'"
                :placeholder="configValuePlaceholder(row)"
              />
              <em>{{ row.remark || '平台运行配置' }}</em>
              <i>{{ row.status || '启用' }}</i>
              <span class="settings-config-actions">
                <button
                  v-if="editingConfigId !== row.id"
                  type="button"
                  class="filter-reset-btn tiny-btn"
                  @click="startEditConfig(row)"
                >
                  编辑
                </button>
                <template v-else>
                  <button type="button" class="primary-btn small-btn" :disabled="savingConfig" @click="saveConfigRow(row)">保存</button>
                  <button type="button" class="filter-reset-btn tiny-btn" @click="cancelEditConfig">取消</button>
                </template>
              </span>
            </div>
            <div v-if="!filteredConfigRows.length" class="mini-empty">该分类暂无配置项。</div>
          </template>
        </div>

        <div v-else class="feature-table">
          <div class="feature-table-head"><span>平台</span><span>问题</span><span>排名</span><span>状态</span><span>快照</span></div>
          <div v-for="item in recentSubtasks.slice(0, 8)" :key="item.subtask_id" class="feature-table-row">
            <span>{{ platformLabelMap[item.platform] || item.platform }}</span>
            <b>{{ item.prompt }}</b>
            <span>{{ item.mention_position ? `第${item.mention_position}位` : '-' }}</span>
            <em>{{ monitorStatusLabelMap[item.status || ''] || item.status || '-' }}</em>
            <a
              v-if="externalLink(item.page_screenshot)"
              :href="externalLink(item.page_screenshot)!"
              target="_blank"
              rel="noopener noreferrer"
            >打开</a>
            <span v-else>待返回</span>
          </div>
          <div v-if="!recentSubtasks.length" class="mini-empty">暂无检测明细，真实任务完成后自动显示。</div>
        </div>
      </article>
    </section>
  </section>
</template>
