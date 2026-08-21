<script setup lang="ts">
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Download,
  FileText,
  Lightbulb,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Stethoscope,
  Target,
  TimerReset,
  Zap,
} from '@lucide/vue'
import { initChart, type ECharts } from '../../../utils/echartsLoader'
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import { useLeadDiagnosis } from '../composables/useLeadDiagnosis'
import RegionMultiSelect from '../components/RegionMultiSelect.vue'
import { rankToneClass, renderEntityRankTrendChart, renderMentionRateBarChart } from '../composables/leadDiagnosisCharts'
import {
  classifyLeadConfigPrompt,
  displayOrEmpty,
} from '../composables/leadDiagnosisConfigDisplay'
import '../../../styles/lead-diagnosis.css'

const {
  loading,
  saving,
  exporting,
  exportingFormat,
  exportProgress,
  detailLoading,
  previewHtmlLoading,
  previewHtmlUrl,
  loadError,
  selectedId,
  detail,
  keywordFilter,
  statusFilter,
  showCreatePanel,
  createStep,
  detailTab,
  createForm,
  canCreate,
  canExport,
  canEditRegions,
  filteredRecords,
  statsSummary,
  kpis,
  diagnosisBlock,
  platformStats,
  promptAnalytics,
  sourceAnalysis,
  rankTrend,
  trackedEntities,
  regionLabels,
  diagnosisPlatformOptions,
  promptTemplates,
  scheduleSlots,
  scheduleDays,
  scheduleDaysMin,
  scheduleDaysMax,
  scheduleDaysSuggestMin,
  scheduleDaysSuggestMax,
  scheduleTotal,
  createScheduleTotal,
  clampScheduleDays,
  runStatusLabels,
  statusLabels,
  platformLabelMap,
  formatDateTime,
  formatLeadCreator,
  filledPromptCount,
  promptQuality,
  generateBalancedPrompts,
  scheduleTimeline,
  schedulePlanSummary,
  progressPercent,
  activeInflightRunCount,
  isLeadScheduleSlotDue,
  healthTone,
  selectRecord,
  openCreatePanel,
  closeCreatePanel,
  toggleCreatePlatform,
  applyPromptTemplate,
  nextCreateStep,
  handleRefresh,
  handleForceRun,
  handleCancel,
  handleFinalizeEarly,
  handleRunSlot,
  canRunScheduleSlot,
  submittingSlotKey,
  handleExport,
} = useLeadDiagnosis()

const workflowSteps = [
  { title: '录入客户画像', desc: '品牌、竞品与核心问题', icon: Target },
  { title: '多日定时采集', desc: `默认 ${scheduleDays} 天 × ${scheduleSlots.join(' / ')}（可改天数）`, icon: TimerReset },
  { title: '生成诊断结论', desc: '聚合平台表现、排名与引用信源', icon: Sparkles },
  { title: '交付 PDF', desc: '可直接用于售前沟通', icon: FileText },
]

function slotClass(state: string) {
  if (state === 'completed') return 'is-done'
  if (state === 'failed') return 'is-failed'
  if (state === 'submitted' || state === 'pending') return 'is-running'
  return ''
}

function formatRank(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  if (Number.isNaN(number)) return String(value)
  return Number.isInteger(number) ? String(number) : number.toFixed(1)
}

function listProgress(item: { completed_run_count: number; schedule_total_count?: number }) {
  const total = item.schedule_total_count ?? scheduleTotal
  return Array.from({ length: total }, (_, index) => {
    if (index < item.completed_run_count) return 'done'
    if (index === item.completed_run_count && item.completed_run_count < total) return 'running'
    return ''
  })
}

/** 2026-08-21 - 任务配置展示建单全量；空字段统一「未填写」 */
const configPromptRows = computed(() => {
  const row = detail.value
  if (!row) return []
  const brand = String(row.brand_name || '')
  const aliases = Array.isArray(row.brand_aliases) ? row.brand_aliases.map(String) : []
  return (row.prompts || []).map((prompt, index) => {
    const meta = classifyLeadConfigPrompt(prompt, brand, aliases)
    return {
      index: index + 1,
      prompt: String(prompt || '').trim() || '未填写',
      ...meta,
    }
  })
})

const configPlatformConfigured = computed(() => {
  const codes = detail.value?.platforms || []
  if (!codes.length) return [] as Array<{ code: string; label: string }>
  return codes.map((code) => ({
    code,
    label: platformLabelMap[code] || code,
  }))
})

/** 2026-08-21 - 任务配置分块默认折叠，避免整页过长 */
const configSectionOpen = ref<Record<string, boolean>>({
  brand: true,
  scope: false,
  prompts: true,
  meta: false,
})

function toggleConfigSection(key: string) {
  configSectionOpen.value = {
    ...configSectionOpen.value,
    [key]: !configSectionOpen.value[key],
  }
}

const promptTrendRefs = new Map<number, HTMLElement>()
const promptMentionRefs = new Map<number, HTMLElement>()
const promptTrendCharts = new Map<number, ECharts>()
const promptMentionCharts = new Map<number, ECharts>()

function bindPromptTrendRef(index: number, el: Element | null) {
  if (el instanceof HTMLElement) promptTrendRefs.set(index, el)
}

function bindPromptMentionRef(index: number, el: Element | null) {
  if (el instanceof HTMLElement) promptMentionRefs.set(index, el)
}

function disposePromptCharts() {
  for (const chart of promptTrendCharts.values()) chart.dispose()
  for (const chart of promptMentionCharts.values()) chart.dispose()
  promptTrendCharts.clear()
  promptMentionCharts.clear()
}

async function renderPromptCharts() {
  if (detailTab.value !== 'queries' || !promptAnalytics.value.length || !detail.value) {
    disposePromptCharts()
    return
  }
  await nextTick()
  const brand = detail.value.brand_name
  const entities = trackedEntities.value.length
    ? trackedEntities.value
    : [brand, ...(detail.value.competitors || [])].filter(Boolean).slice(0, 4)

  for (const [index, block] of promptAnalytics.value.entries()) {
    const roundTrend = (block.round_trend as Array<Record<string, unknown>> | undefined) || []
    const mentionTable = (block.mention_table as Array<Record<string, unknown>> | undefined) || []
    const trendEl = promptTrendRefs.get(index)
    if (trendEl && roundTrend.length) {
      let chart = promptTrendCharts.get(index)
      if (!chart) {
        chart = await initChart(trendEl, 'diagnosis')
        promptTrendCharts.set(index, chart)
      }
      renderEntityRankTrendChart(chart, roundTrend, brand, entities as string[])
    }
    const mentionEl = promptMentionRefs.get(index)
    if (mentionEl && mentionTable.length) {
      let chart = promptMentionCharts.get(index)
      if (!chart) {
        chart = await initChart(mentionEl, 'diagnosis')
        promptMentionCharts.set(index, chart)
      }
      renderMentionRateBarChart(chart, mentionTable, detail.value?.brand_name || '')
    }
  }
}

watch([detailTab, promptAnalytics, trackedEntities, selectedId], () => {
  void renderPromptCharts()
}, { deep: true })

onUnmounted(() => {
  disposePromptCharts()
})
</script>

<template>
  <section class="lead-workspace" :class="{ 'is-creating': showCreatePanel }">
    <div v-if="showCreatePanel" class="lead-create">
      <div class="lead-create-hero">
        <div>
          <span class="lead-eyebrow">售前诊断任务</span>
          <h2>创建售前 AI 可见度诊断</h2>
          <p>先生成标准诊断问法，再采集 AI 平台回答，输出可交付报告。</p>
        </div>
        <button type="button" class="lead-icon-btn" @click="closeCreatePanel">
          <ArrowLeft :size="17" /> 返回列表
        </button>
      </div>

      <div class="lead-step-bar">
        <span :class="{ active: createStep === 1 }"><b>01</b> 客户与品牌</span>
        <span :class="{ active: createStep === 2 }"><b>02</b> 诊断问法</span>
      </div>

      <div v-if="createStep === 1" class="lead-form lead-form-card">
        <div class="lead-form-grid">
          <label class="lead-field lead-field-wide">
            <span>品牌名称 *</span>
            <input v-model="createForm.brand_name" placeholder="例如：客户品牌全称" />
          </label>
          <label class="lead-field lead-field-wide">
            <span>品牌别名 / 露出词（可选）</span>
            <!-- 2026-08-20 - 别名示例勿写死旧客户名 -->
            <input v-model="createForm.brand_aliases" placeholder="多个用逗号分隔，例如：品牌简称, 品牌别称" />
          </label>
          <label class="lead-field lead-field-wide">
            <span>官网 URL（强烈建议）</span>
            <input v-model="createForm.website_url" placeholder="https://www.example.com" />
          </label>
          <label class="lead-field">
            <span>所属行业 / 业务类型</span>
            <input v-model="createForm.industry" placeholder="例如：服饰辅料 / RPA / 户外广告" />
          </label>
          <label class="lead-field">
            <span>主要产品 / 采购场景</span>
            <input v-model="createForm.product_focus" placeholder="例如：拉链 / 智能体平台" />
          </label>
          <label class="lead-field lead-field-wide">
            <span>主要竞品</span>
            <input v-model="createForm.competitors" placeholder="多个竞品用逗号分隔，例如：竞品A, 竞品B" />
          </label>
          <label v-if="canEditRegions" class="lead-field lead-field-wide">
            <span>监测地区</span>
            <RegionMultiSelect v-model="createForm.region_codes" />
          </label>
          <div class="lead-field lead-field-wide lead-platform-field">
            <span>诊断平台 *（已选 {{ createForm.platforms.length }}）</span>
            <div class="platform-check-grid compact">
              <label
                v-for="platform in diagnosisPlatformOptions"
                :key="platform.code"
                class="platform-check"
                :class="{ 'is-selected': createForm.platforms.includes(platform.code) }"
                @click.prevent="toggleCreatePlatform(platform.code)"
              >
                <input
                  type="checkbox"
                  tabindex="-1"
                  :checked="createForm.platforms.includes(platform.code)"
                />
                <PlatformBadge
                  :code="platform.code"
                  size="sm"
                  :label="platform.name || platformLabelMap[platform.code] || platform.code"
                />
              </label>
            </div>
          </div>
          <label class="lead-field">
            <span>诊断天数 *（建议 {{ scheduleDaysSuggestMin }}–{{ scheduleDaysSuggestMax }}，默认 {{ scheduleDays }}）</span>
            <input
              v-model.number="createForm.schedule_days"
              type="number"
              :min="scheduleDaysMin"
              :max="scheduleDaysMax"
              step="1"
              @blur="createForm.schedule_days = clampScheduleDays(createForm.schedule_days)"
            />
          </label>
          <label class="lead-field lead-field-wide">
            <span>销售备注</span>
            <textarea v-model="createForm.contact_note" rows="3" placeholder="客户来源、行业背景、意向度、重点关注点" />
          </label>
        </div>
        <div class="lead-form-hint">
          <Lightbulb :size="16" />
          <span>
            提交后共 <b>{{ createScheduleTotal }}</b> 次抓取
            （{{ clampScheduleDays(createForm.schedule_days) }} 天 × 每天 <b>{{ scheduleSlots.join(' / ') }}</b>）；
            若创建时已错过当日早场，剩余时段顺延，全部完成后可导出 PDF。
          </span>
        </div>
        <div class="lead-form-actions">
          <button type="button" class="lead-secondary-btn" @click="closeCreatePanel">取消</button>
          <button type="button" class="lead-primary-btn" @click="nextCreateStep">
            下一步 <ArrowRight :size="16" />
          </button>
        </div>
      </div>

      <div v-else class="lead-form lead-form-card">
        <div class="lead-form-hint" style="margin-bottom:12px">
          <Lightbulb :size="16" />
          <span>
            问法质量：非品牌 <b>{{ promptQuality.nonbrandN }}</b> / 3，品牌 <b>{{ promptQuality.brandN }}</b> / 2，总计 <b>{{ promptQuality.total }}</b> / 5。
            建议非品牌≥3、品牌≥2，否则获客主 KPI 可能暂无。
          </span>
        </div>
        <div class="lead-form-actions" style="justify-content:flex-start;margin-bottom:12px">
          <button type="button" class="lead-secondary-btn" @click="generateBalancedPrompts">
            <Sparkles :size="15" /> 一键生成标准问法
          </button>
        </div>
        <div class="lead-prompt-stack">
          <div v-for="(tpl, index) in promptTemplates" :key="index" class="lead-prompt-row">
            <label class="lead-field lead-prompt-field">
              <span>
                问题 {{ index + 1 }}{{ index === 0 ? ' *' : '' }}
                <em style="margin-left:6px;font-style:normal;color:#6b7280">{{ tpl.lane === 'brand' ? '品牌防守' : '非品牌获客' }}</em>
              </span>
              <input v-model="createForm.prompts[index]" :placeholder="tpl.value" />
            </label>
            <button type="button" class="lead-template-btn" @click="applyPromptTemplate(index)">
              {{ tpl.label }}
            </button>
          </div>
        </div>
        <label class="lead-check-row">
          <input v-model="createForm.start_immediately" type="checkbox" />
          <span>创建后立即启动第 1 次抓取（计入计划次数），其余场次仍按计划自动执行</span>
        </label>
        <div class="lead-form-hint">
          <Lightbulb :size="16" />
          <span>已填写 <b>{{ filledPromptCount }}</b> / 5 个问题。非品牌问法不含品牌名；品牌问法含品牌名并计入防守口径。</span>
        </div>
        <div class="lead-form-actions">
          <button type="button" class="lead-secondary-btn" @click="createStep = 1">上一步</button>
          <button type="button" class="lead-primary-btn" :disabled="saving" @click="nextCreateStep">
            {{ saving ? '提交中...' : '提交诊断任务' }}
          </button>
        </div>
      </div>
    </div>

    <template v-else>
      <aside class="lead-rail">
        <div class="lead-rail-head">
          <div>
            <span class="lead-eyebrow">Pre-sales GEO</span>
            <h3>售前诊断</h3>
            <p>销售内用 · 潜客转化材料</p>
          </div>
        </div>

        <button v-if="canCreate" type="button" class="lead-create-btn" @click="openCreatePanel">
          <Plus :size="16" /> 新建诊断
        </button>

        <div class="lead-rail-stats">
          <div class="lead-stat"><span>全部任务</span><strong>{{ statsSummary.total }}</strong></div>
          <div class="lead-stat"><span>进行中</span><strong>{{ statsSummary.collecting }}</strong></div>
          <div class="lead-stat"><span>可交付</span><strong>{{ statsSummary.ready }}</strong></div>
        </div>

        <label class="lead-search">
          <Search :size="15" />
          <input v-model="keywordFilter" placeholder="搜索品牌" />
        </label>

        <div class="lead-rail-filters">
          <button type="button" :class="{ active: statusFilter === '' }" @click="statusFilter = ''">全部</button>
          <button
            v-for="(label, value) in statusLabels"
            :key="value"
            type="button"
            :class="{ active: statusFilter === value }"
            @click="statusFilter = value as typeof statusFilter"
          >
            {{ label }}
          </button>
        </div>

        <div v-if="loadError" class="lead-alert">{{ loadError }}</div>
        <div v-else-if="loading" class="lead-empty">加载诊断任务中...</div>
        <div v-else-if="!filteredRecords.length" class="lead-empty">
          {{ keywordFilter || statusFilter ? '没有匹配的任务' : '暂无诊断任务' }}
        </div>
        <div v-else class="lead-rail-list">
          <article
            v-for="item in filteredRecords"
            :key="item.id"
            class="lead-rail-item"
            :class="{ active: selectedId === item.id }"
            @click="selectRecord(item.id)"
          >
            <div class="lead-rail-item-top">
              <b>{{ item.brand_name }}</b>
              <span class="lead-badge" :class="item.status">{{ statusLabels[item.status] }}</span>
            </div>
            <p>诊断日期 {{ item.diagnosis_date }}</p>
            <p v-if="item.creator" class="lead-rail-creator">创建人 {{ formatLeadCreator(item.creator) }}</p>
            <div class="lead-rail-progress">
              <i v-for="(state, idx) in listProgress(item)" :key="idx" :class="state" />
            </div>
          </article>
        </div>
      </aside>

      <main class="lead-stage">
        <div class="lead-stage-hero">
          <div>
            <span class="lead-eyebrow">Sales Enablement</span>
            <h1>潜客 AI 可见度诊断台</h1>
            <p>把采集、判断、结论和交付放在一个页面里，让销售能快速说明客户在 AI 搜索中的机会与风险。</p>
          </div>
          <div class="lead-hero-card">
            <b>{{ statsSummary.ready }}</b>
            <span>份报告可交付</span>
          </div>
        </div>

        <div v-if="!selectedId" class="lead-welcome">
          <div class="lead-welcome-icon"><Stethoscope :size="28" /></div>
          <h2>选择左侧任务查看诊断详情</h2>
          <p>也可以新建一条售前诊断，为潜在客户生成可演示、可导出的 GEO 诊断材料。</p>
          <div class="lead-workflow">
            <article v-for="(step, index) in workflowSteps" :key="step.title" class="lead-workflow-step">
              <component :is="step.icon" :size="20" />
              <span>{{ String(index + 1).padStart(2, '0') }}</span>
              <b>{{ step.title }}</b>
              <small>{{ step.desc }}</small>
            </article>
          </div>
        </div>

        <template v-else>
          <header class="lead-detail-head">
            <div>
              <span class="lead-badge" :class="detail?.status">{{ detail ? statusLabels[detail.status] : '' }}</span>
              <h2>{{ detail?.brand_name }}</h2>
              <small>
                诊断日期 {{ detail?.diagnosis_date }}
                <template v-if="detail?.creator"> · 创建人 {{ formatLeadCreator(detail.creator) }}</template>
              </small>
            </div>
            <div class="lead-detail-actions">
              <button type="button" class="lead-secondary-btn small" :disabled="detailLoading" @click="handleRefresh">
                <RefreshCw :size="16" /> 刷新进度
              </button>
              <button
                v-if="canCreate && (detail?.status === 'pending' || detail?.status === 'collecting')"
                type="button"
                class="lead-secondary-btn small"
                @click="handleCancel"
              >
                取消任务
              </button>
              <button
                v-if="canCreate && (detail?.status === 'pending' || detail?.status === 'collecting')"
                type="button"
                class="lead-secondary-btn small"
                @click="handleFinalizeEarly"
              >
                提前结束并生成报告
              </button>
              <button v-if="canCreate && detail?.status !== 'ready' && detail?.status !== 'canceled' && detail?.status !== 'failed'" type="button" class="lead-secondary-btn small" @click="handleForceRun">
                <Zap :size="16" /> 立即抓取下一档
              </button>
              <button v-if="canExport && detail?.status === 'ready'" type="button" class="lead-primary-btn small" :disabled="exporting" @click="handleExport('html')">
                <Download :size="16" /> {{ exportingFormat === 'html' ? (exportProgress || '导出中…') : '下载 HTML' }}
              </button>
              <!-- 2026-08-12 - 诊断改驾驶舱 - 暂隐藏 PDF，仅 HTML -->
            </div>
          </header>

          <div v-if="detailLoading && !detail" class="lead-empty lead-empty-stage">加载详情中...</div>

          <template v-else-if="detail">
            <div class="lead-kpi-row">
              <div class="lead-kpi">
                <label>健康分</label>
                <strong :class="healthTone(Number(detail.health_score ?? diagnosisBlock.health_score))">
                  {{ detail.health_score ?? diagnosisBlock.health_score ?? '-' }}
                </strong>
                <span>综合可见度</span>
              </div>
              <div class="lead-kpi">
                <label>品牌提及率</label>
                <strong>{{ kpis.mention_rate ?? '-' }}<small v-if="kpis.mention_rate != null">%</small></strong>
                <span>被 AI 推荐占比</span>
              </div>
              <div class="lead-kpi">
                <label>平均排名</label>
                <strong>{{ formatRank(kpis.avg_rank) }}</strong>
                <span>越靠前越好</span>
              </div>
              <div class="lead-kpi">
                <label>采集进度</label>
                <strong>{{ progressPercent }}%</strong>
                <!-- 2026-08-14 - 计划档 ≠ 子任务数，勿只写 9/9 与驾驶舱 270 对不上 -->
                <span>计划 {{ detail.completed_run_count }}/{{ detail.schedule_total_count ?? scheduleTotal }} 档 · 子任务 {{ Number(kpis.completed_count ?? 0) || '—' }}</span>
              </div>
            </div>

            <nav class="lead-tabs">
              <button type="button" :class="{ active: detailTab === 'progress' }" @click="detailTab = 'progress'">
                <Clock3 :size="14" /> 抓取进度
              </button>
              <button type="button" :class="{ active: detailTab === 'report' }" :disabled="detail.status !== 'ready'" @click="detailTab = 'report'">
                <FileText :size="14" /> 诊断结论
              </button>
              <button type="button" :class="{ active: detailTab === 'queries' }" :disabled="detail.status !== 'ready'" @click="detailTab = 'queries'">
                <Search :size="14" /> 语义词分析
              </button>
              <button type="button" :class="{ active: detailTab === 'sources' }" :disabled="detail.status !== 'ready'" @click="detailTab = 'sources'">
                <BarChart3 :size="14" /> 引用信源
              </button>
              <button type="button" :class="{ active: detailTab === 'platforms' }" :disabled="!platformStats.length" @click="detailTab = 'platforms'">
                <BarChart3 :size="14" /> 平台表现
              </button>
              <button type="button" :class="{ active: detailTab === 'config' }" @click="detailTab = 'config'">
                任务配置
              </button>
            </nav>

            <section v-if="detailTab === 'progress'" class="lead-panel">
              <div class="lead-panel-title">
                <h3>抓取计划</h3>
                <p>{{ schedulePlanSummary }}</p>
              </div>
              <div class="lead-timeline">
                <article v-for="slot in scheduleTimeline" :key="slot.schedule_key" class="lead-slot" :class="slotClass(slot.state)">
                  <div class="lead-slot-index">
                    <CheckCircle2 v-if="slot.state === 'completed'" :size="20" />
                    <span v-else>{{ slot.index }}</span>
                  </div>
                  <div class="lead-slot-body">
                    <b>第 {{ slot.dayOffset }} 天 · {{ slot.slot }}</b>
                    <small>{{ slot.day }}</small>
                    <small v-if="slot.run">
                      {{ slot.run.prompt_count }} 问题 x {{ slot.run.platform_count }} 平台 · {{ runStatusLabels[slot.run.status] || slot.run.status }}
                    </small>
                    <small v-else-if="activeInflightRunCount >= 2">已有 2 个批次在抓取，请等待完成后再手动提交。</small>
                    <small v-else-if="!isLeadScheduleSlotDue(slot.day, slot.slot)">未到计划时间，系统将自动执行。</small>
                    <small v-else>等待到点自动执行，或点击右侧「抓取此次」。</small>
                  </div>
                  <div class="lead-slot-actions">
                    <button
                      v-if="canCreate && detail?.status !== 'ready' && canRunScheduleSlot(slot.state, slot)"
                      type="button"
                      class="lead-secondary-btn small"
                      :disabled="submittingSlotKey === slot.schedule_key"
                      @click="handleRunSlot(slot.schedule_key, slot.label)"
                    >
                      <Zap :size="14" />
                      {{ submittingSlotKey === slot.schedule_key ? '提交中…' : '抓取此次' }}
                    </button>
                    <span v-else class="lead-badge" :class="slot.state === 'completed' ? 'ready' : slot.state === 'failed' ? 'failed' : 'collecting'">
                      {{ slot.run ? (runStatusLabels[slot.run.status] || slot.run.status) : '待执行' }}
                    </span>
                  </div>
                </article>
              </div>
            </section>

            <section v-else-if="detailTab === 'report'" class="lead-panel lead-panel-cockpit">
              <div class="lead-panel-title">
                <h3>诊断结论</h3>
                <p>态势感知平台（与下载 HTML 同源）</p>
              </div>
              <div v-if="detail.status !== 'ready'" class="lead-form-hint">
                <Lightbulb :size="16" />
                <span>诊断尚未完成，请等待计划抓取全部结束或刷新进度。</span>
              </div>
              <div v-else class="lead-cockpit-preview">
                <div v-if="previewHtmlLoading && !previewHtmlUrl" class="lead-empty lead-empty-stage">驾驶舱加载中…</div>
                <iframe
                  v-else-if="previewHtmlUrl"
                  :key="previewHtmlUrl"
                  class="lead-html-frame"
                  :src="previewHtmlUrl"
                  title="售前诊断驾驶舱预览"
                />
                <div v-else class="lead-empty lead-empty-stage">预览暂不可用，可尝试下载 HTML</div>
              </div>
            </section>

            <section v-else-if="detailTab === 'queries'" class="lead-panel">
              <div class="lead-panel-title">
                <h3>语义词排名与回答命中</h3>
                <p>按每个检测问题汇总品牌、竞品及头部机构的排名与回答命中表现（主报告提及率以格级露出为准）。</p>
              </div>
              <div v-if="!promptAnalytics.length" class="lead-form-hint">
                <Lightbulb :size="16" /><span>暂无分语义词数据。</span>
              </div>
              <div v-for="(block, index) in promptAnalytics" :key="String(block.prompt)" class="lead-query-block">
                <header>
                  <b>{{ block.prompt }}</b>
                  <small>
                    样本 {{ block.sample_count }} · 回答命中率 {{ block.brand_mention_rate }}% · 平均排名 {{ formatRank(block.brand_avg_rank) }}
                  </small>
                </header>
                <div v-if="(block.round_trend as Array<Record<string, unknown>>)?.length" class="lead-query-charts">
                  <div class="lead-query-chart-card">
                    <div class="lead-query-subtitle">问题{{ index + 1 }}趋势图</div>
                    <div :ref="el => bindPromptTrendRef(index, el as Element | null)" class="lead-rank-trend-chart" />
                  </div>
                </div>
                <div v-if="(block.mention_table as Array<Record<string, unknown>>)?.length" class="lead-query-chart-card">
                  <div class="lead-query-subtitle">品牌回答命中率分析</div>
                  <div :ref="el => bindPromptMentionRef(index, el as Element | null)" class="lead-mention-chart" />
                </div>
                <div v-if="(block.round_trend as Array<Record<string, unknown>>)?.length" class="lead-query-subtitle">品牌排名变化趋势</div>
                <div v-if="(block.round_trend as Array<Record<string, unknown>>)?.length" class="lead-rank-change-grid head">
                  <span>日期</span><span>{{ block.prompt }}</span>
                </div>
                <div
                  v-for="row in (block.round_trend as Array<Record<string, unknown>> || [])"
                  :key="String(row.schedule_key)"
                  class="lead-rank-change-grid"
                >
                  <span>{{ row.schedule_label }}</span>
                  <span class="lead-rank-cell" :class="rankToneClass(row.avg_rank)">{{ formatRank(row.avg_rank) }}</span>
                </div>
                <div v-if="(block.ranking_list as Array<Record<string, unknown>>)?.length" class="lead-query-subtitle">最近排名列表</div>
                <div v-if="(block.ranking_list as Array<Record<string, unknown>>)?.length" class="lead-query-grid head">
                  <span>品牌</span><span>分类</span><span>排名</span><span>标签</span>
                </div>
                <div
                  v-for="row in (block.ranking_list as Array<Record<string, unknown>> || [])"
                  :key="`${row.name}-${row.category}`"
                  class="lead-query-grid"
                  :class="{ 'is-brand': row.is_brand, 'is-competitor': row.is_competitor }"
                >
                  <b>{{ row.name }}</b>
                  <span>{{ row.category || '默认分类' }}</span>
                  <span>{{ formatRank(row.rank) }}</span>
                  <span>{{ row.is_brand ? '目标品牌' : row.is_competitor ? '竞品' : '—' }}</span>
                </div>
                <div class="lead-query-subtitle">回答命中率统计</div>
                <div class="lead-query-grid head mention">
                  <span>品牌</span><span>命中次数</span><span>回答命中率</span><span>平均排名</span>
                </div>
                <div
                  v-for="row in (block.mention_table as Array<Record<string, unknown>> || [])"
                  :key="`m-${row.name}`"
                  class="lead-query-grid mention"
                  :class="{ 'is-brand': row.is_brand, 'is-competitor': row.is_competitor }"
                >
                  <b>{{ row.name }}</b>
                  <span>{{ row.mention_count }}/{{ row.sample_count }}</span>
                  <span>{{ row.mention_rate }}%</span>
                  <span>{{ formatRank(row.avg_rank) }}</span>
                </div>
              </div>
            </section>

            <section v-else-if="detailTab === 'sources'" class="lead-panel">
              <div class="lead-panel-title">
                <h3>引用网站分析</h3>
                <p>统计 AI 回答引用域名及与品牌提及的关联度。</p>
              </div>
              <div class="lead-form-hint">
                <Lightbulb :size="16" />
                <span>{{ sourceAnalysis.coverage_note || '暂无引用信源统计。' }}</span>
              </div>
              <div v-if="(sourceAnalysis.domain_stats as Array<Record<string, unknown>>)?.length" class="lead-query-grid head source">
                <span>域名</span><span>引用次数</span><span>品牌相关</span><span>平台数</span>
              </div>
              <div
                v-for="row in (sourceAnalysis.domain_stats as Array<Record<string, unknown>> || [])"
                :key="String(row.domain)"
                class="lead-query-grid source"
              >
                <b>{{ row.domain }}</b>
                <span>{{ row.count }}</span>
                <span>{{ row.brand_related_count }}</span>
                <span>{{ (row.platforms as string[] | undefined)?.length || 0 }}</span>
              </div>
            </section>

            <section v-else-if="detailTab === 'platforms'" class="lead-panel">
              <div class="lead-panel-title">
                <h3>AI 平台表现</h3>
                <p>按平台统计样本量、品牌提及率与平均排名。</p>
              </div>
              <div v-if="!platformStats.length" class="lead-form-hint">
                <Lightbulb :size="16" /><span>暂无平台数据。</span>
              </div>
              <div v-else class="lead-platform-grid">
                <span>平台</span><span>样本</span><span>提及率</span><span>平均排名</span>
                <template v-for="row in platformStats" :key="String(row.platform)">
                  <b>{{ platformLabelMap[String(row.platform)] || row.platform }}</b>
                  <b>{{ row.completed }}/{{ row.total }}</b>
                  <b>{{ row.mention_rate }}%</b>
                  <b>{{ formatRank(row.avg_rank) }}</b>
                </template>
              </div>
            </section>

            <section v-else class="lead-panel">
              <div class="lead-panel-title">
                <h3>任务配置</h3>
                <p>建单完整输入（只读）。点击标题展开 / 收起各块。</p>
              </div>

              <div class="lead-config-accordion">
                <section class="lead-config-block" :class="{ open: configSectionOpen.brand }">
                  <button type="button" class="lead-config-block-head" @click="toggleConfigSection('brand')">
                    <span>品牌与上下文</span>
                    <ChevronDown :size="16" />
                  </button>
                  <div v-show="configSectionOpen.brand" class="lead-config-block-body">
                    <div class="lead-config-list">
                      <div><strong>品牌名称</strong><span>{{ displayOrEmpty(detail.brand_name) }}</span></div>
                      <div><strong>露出词 / 别名</strong><span>{{ displayOrEmpty((detail.brand_aliases || []).join('、')) }}</span></div>
                      <div><strong>官网</strong><span>{{ displayOrEmpty(detail.lead_context?.website_url) }}</span></div>
                      <div><strong>行业</strong><span>{{ displayOrEmpty(detail.lead_context?.industry) }}</span></div>
                      <div><strong>产品焦点</strong><span>{{ displayOrEmpty(detail.lead_context?.product_focus) }}</span></div>
                      <div><strong>采购场景</strong><span>{{ displayOrEmpty(detail.lead_context?.purchase_scenario) }}</span></div>
                      <div><strong>来源备注</strong><span>{{ displayOrEmpty(detail.lead_context?.source) }}</span></div>
                      <div><strong>竞品</strong><span>{{ displayOrEmpty((detail.competitors || []).join('、')) }}</span></div>
                    </div>
                  </div>
                </section>

                <section class="lead-config-block" :class="{ open: configSectionOpen.scope }">
                  <button type="button" class="lead-config-block-head" @click="toggleConfigSection('scope')">
                    <span>监测范围</span>
                    <ChevronDown :size="16" />
                  </button>
                  <div v-show="configSectionOpen.scope" class="lead-config-block-body">
                    <div class="lead-config-list">
                      <div class="lead-config-platforms">
                        <strong>诊断平台</strong>
                        <div v-if="configPlatformConfigured.length" class="lead-config-platform-badges">
                          <PlatformBadge
                            v-for="item in configPlatformConfigured"
                            :key="`cfg-${item.code}`"
                            :code="item.code"
                            size="sm"
                            :label="item.label"
                          />
                        </div>
                        <span v-else class="lead-config-muted">未填写</span>
                      </div>
                      <div><strong>监测地区</strong><span>{{ displayOrEmpty(regionLabels(detail.region_codes)) }}</span></div>
                      <div><strong>诊断天数</strong><span>{{ detail.schedule_days != null ? `${detail.schedule_days} 天` : '未填写' }}</span></div>
                      <div><strong>抓取时段</strong><span>{{ displayOrEmpty((detail.schedule_times || scheduleSlots).join('、')) }}</span></div>
                      <div>
                        <strong>抓取计划</strong>
                        <span>
                          共 {{ detail.schedule_total_count ?? scheduleTotal }} 次
                          （{{ detail.schedule_days || scheduleDays }} 天 × 每日 {{ (detail.schedule_times || scheduleSlots).length }} 档）
                        </span>
                      </div>
                    </div>
                  </div>
                </section>

                <section class="lead-config-block" :class="{ open: configSectionOpen.prompts }">
                  <button type="button" class="lead-config-block-head" @click="toggleConfigSection('prompts')">
                    <span>检测问法（{{ configPromptRows.length }}）</span>
                    <ChevronDown :size="16" />
                  </button>
                  <div v-show="configSectionOpen.prompts" class="lead-config-block-body">
                    <div v-if="!configPromptRows.length" class="lead-form-hint">
                      <Lightbulb :size="16" /><span>未填写检测问题。</span>
                    </div>
                    <ol v-else class="lead-config-prompts">
                      <li v-for="row in configPromptRows" :key="`${row.index}-${row.prompt}`">
                        <div class="lead-config-prompt-meta">
                          <b>问题 {{ row.index }}</b>
                          <em :class="row.isBrand ? 'is-brand' : 'is-acq'">{{ row.laneLabel }}</em>
                          <em class="is-report">报告归类 · {{ row.reportLabel }}</em>
                        </div>
                        <p>{{ row.prompt }}</p>
                      </li>
                    </ol>
                  </div>
                </section>

                <section class="lead-config-block" :class="{ open: configSectionOpen.meta }">
                  <button type="button" class="lead-config-block-head" @click="toggleConfigSection('meta')">
                    <span>创建与计划</span>
                    <ChevronDown :size="16" />
                  </button>
                  <div v-show="configSectionOpen.meta" class="lead-config-block-body">
                    <div class="lead-config-list">
                      <div><strong>创建人</strong><span>{{ detail.creator ? formatLeadCreator(detail.creator) : '未填写' }}</span></div>
                      <div><strong>登录账号</strong><span>{{ displayOrEmpty(detail.creator?.username) }}</span></div>
                      <div><strong>创建时间</strong><span>{{ displayOrEmpty(formatDateTime(detail.created_at)) }}</span></div>
                      <div><strong>更新时间</strong><span>{{ displayOrEmpty(formatDateTime(detail.updated_at)) }}</span></div>
                      <div><strong>诊断日期</strong><span>{{ displayOrEmpty(detail.diagnosis_date) }}</span></div>
                      <div><strong>计划截止</strong><span>{{ displayOrEmpty(detail.plan_end_date) }}</span></div>
                      <div><strong>状态</strong><span>{{ statusLabels[detail.status] || detail.status }}</span></div>
                      <div><strong>销售备注</strong><span>{{ displayOrEmpty(detail.contact_note) }}</span></div>
                    </div>
                  </div>
                </section>
              </div>
            </section>
          </template>
        </template>
      </main>
    </template>
  </section>
</template>
