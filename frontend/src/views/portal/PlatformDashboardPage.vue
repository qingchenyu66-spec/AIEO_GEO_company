<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Activity, AlertTriangle, ArrowRight, BarChart3, Building2, Clock3, Database, FileBarChart, Gauge, RefreshCw, Settings, Sparkles, WalletCards, Zap } from '@lucide/vue'
import { getPlatformOverview, type MolizhishuBalance, type PlatformOverview } from '../../services/management'
import { getDeepseekBalance, getMolizhishuBalance, type DeepseekBalance } from '../../services/platforms'
import { extractErrorDetail } from '../../utils/requestError'
import { initChart, type ECharts } from '../../utils/echartsLoader'
import { sortPlatformRows } from './platformOrder'

const props = defineProps<{
  platformLabelMap: Record<string, string>
  monitorStatusLabelMap: Record<string, string>
  navigateTo: (menuCode: string) => void
}>()

const overview = ref<PlatformOverview | null>(null)
const molizhishuBalance = ref<MolizhishuBalance | null>(null)
const deepseekBalance = ref<DeepseekBalance | null>(null)
const loading = ref(false)
const errorText = ref('')
const taskCompletionChartRef = ref<HTMLDivElement | null>(null)
let taskCompletionChart: ECharts | null = null

const platformStats = computed(() => sortPlatformRows(overview.value?.platform_stats || []))

function cleanDashboardLog(value: string | null | undefined, fallback = '历史编码异常记录，原文不可恢复') {
  const text = String(value || '').trim()
  if (!text) return '-'
  const questionMarks = (text.match(/\?/g) || []).length
  if (questionMarks >= 3 && questionMarks / Math.max(1, text.length) > 0.25) return fallback
  return text
}

function formatBalanceValue(
  balance: (MolizhishuBalance & { display_value?: string | null; currency?: string | null }) | null | undefined,
  currencyFallback = '¥',
) {
  if (!balance) return '--'
  if (balance.available) {
    if (balance.display_value) return balance.display_value
    const text = balance.current_balance_text ?? balance.current_balance
    if (text == null) return '--'
    const symbol = balance.currency === 'USD' ? '$' : balance.currency === 'CNY' ? '¥' : currencyFallback
    return `${symbol} ${text}`
  }
  return balance.error ? '查询失败' : '--'
}

function balanceNote(balance: (MolizhishuBalance & { is_available?: boolean | null }) | null | undefined) {
  if (!balance) return undefined
  const parts: string[] = []
  if (balance.fetched_at) parts.push(`更新于 ${balance.fetched_at}`)
  if (balance.is_available === false) parts.push('余额不足')
  return parts.join(' · ') || undefined
}

const kpiCards = computed(() => {
  const kpis = overview.value?.kpis
  const deepseek = deepseekBalance.value ?? overview.value?.deepseek_balance
  return [
    { label: '今日任务', value: String(kpis?.today_tasks ?? 0), note: `已完成 ${kpis?.today_completed_tasks ?? 0}`, icon: Clock3, tone: 'blue' },
    { label: '异常任务', value: String(kpis?.today_failed_tasks ?? 0), note: '失败 / 停止 / 待复核', icon: AlertTriangle, tone: (kpis?.today_failed_tasks ?? 0) > 0 ? 'red' : 'green' },
    { label: '服务中企业', value: String(kpis?.active_tenants ?? 0), note: '当前正常服务客户', icon: Building2, tone: 'green' },
    { label: '今日消耗', value: String(kpis?.today_cost ?? 0), note: '模力接口扣费', icon: WalletCards, tone: 'cyan' },
    { label: 'DeepSeek 余额', value: formatBalanceValue(deepseek), note: deepseek?.available ? '报告 / 知识库 / 情绪词' : (deepseek?.error || '未配置 API Key'), icon: Sparkles, tone: deepseek?.available ? 'purple' : 'amber' },
    { label: '即将到期', value: String(kpis?.expiring_tenants ?? 0), note: '30 天内到期', icon: FileBarChart, tone: (kpis?.expiring_tenants ?? 0) > 0 ? 'amber' : 'green' },
    { label: '接口成功率', value: `${kpis?.api_success_rate ?? 0}%`, note: '今日调度提交', icon: Gauge, tone: 'purple' },
  ]
})

function todoTarget(type: string) {
  if (type === 'renewal') return 'platform.audit'
  if (type === 'failed_task') return 'platform.alerts'
  if (type === 'snapshot_backfill') return 'platform.snapshot_backfill'
  if (type === 'schedule_failed' || type === 'sync_task' || type === 'celery_queue') return 'platform.alerts'
  return 'platform.alerts'
}

const serviceRows = computed(() => {
  const counts = overview.value?.service_counts || {}
  return [
    { label: '服务中', value: counts.active || 0, tone: 'green' },
    { label: '未开始', value: counts.pending || 0, tone: 'slate' },
    { label: '人工停服', value: counts.manual_stopped || 0, tone: 'amber' },
    { label: '已取消', value: counts.canceled || 0, tone: 'slate' },
    { label: '已到期', value: counts.expired || 0, tone: 'red' },
  ]
})

const taskRate = computed(() => {
  const kpis = overview.value?.kpis
  return kpis?.today_tasks ? Math.round(((kpis.today_completed_tasks || 0) / kpis.today_tasks) * 100) : 0
})

const taskSuccessRate = computed(() => {
  const kpis = overview.value?.kpis
  const total = kpis?.today_tasks || 0
  const failed = kpis?.today_failed_tasks || 0
  if (!total) return 100
  return Math.max(0, Math.round(((total - failed) / total) * 100))
})

const customerDataRows = computed(() => {
  const data = overview.value?.customer_data
  return [
    { label: '企业总数', value: data?.tenant_total ?? 0 },
    { label: '服务中企业', value: data?.active_tenants ?? 0 },
    { label: '累计任务', value: data?.task_total ?? 0 },
    { label: '检测子任务', value: data?.subtask_total ?? 0 },
    { label: '信源记录', value: data?.source_count ?? 0 },
  ]
})

const quotaRows = computed(() => {
  const quota = overview.value?.quota_overview
  const balance = molizhishuBalance.value ?? overview.value?.molizhishu_balance
  const deepseek = deepseekBalance.value ?? overview.value?.deepseek_balance
  return [
    { label: '账户余额', value: formatBalanceValue(balance), highlight: true, note: balanceNote(balance) },
    { label: 'DeepSeek 账户余额', value: formatBalanceValue(deepseek), highlight: true, note: balanceNote(deepseek) },
    { label: '累计消耗', value: quota?.used_amount ?? 0 },
    { label: '今日消耗', value: quota?.today_amount ?? 0 },
    { label: '预计月消耗', value: quota?.estimated_month_amount ?? 0 },
    { label: '单条均价', value: quota?.avg_cost_per_subtask ?? 0 },
  ]
})

async function loadOverview() {
  loading.value = true
  errorText.value = ''
  try {
    const [overviewData, balanceData, deepseekData] = await Promise.all([
      getPlatformOverview(),
      getMolizhishuBalance().catch(() => null),
      getDeepseekBalance().catch(() => null),
    ])
    overview.value = overviewData
    molizhishuBalance.value = balanceData ?? overviewData.molizhishu_balance ?? null
    deepseekBalance.value = deepseekData ?? overviewData.deepseek_balance ?? null
  } catch (error: any) {
    errorText.value = extractErrorDetail(error)
  } finally {
    loading.value = false
  }
}

async function renderTaskCompletionChart() {
  if (!taskCompletionChartRef.value) return
  if (!taskCompletionChart) {
    taskCompletionChart = await initChart(taskCompletionChartRef.value, 'dashboard')
  }
  taskCompletionChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}<br />{c}%' },
    color: ['#2d6cdf', '#34c49a'],
    series: [
      {
        type: 'pie',
        radius: ['68%', '86%'],
        center: ['42%', '50%'],
        avoidLabelOverlap: true,
        label: {
          position: 'center',
          formatter: `{value|${taskRate.value}%}\n{name|完成率}`,
          rich: {
            value: { color: '#10233f', fontSize: 28, fontWeight: 800, lineHeight: 36 },
            name: { color: '#6a7f9a', fontSize: 12, lineHeight: 18 },
          },
        },
        labelLine: { show: false },
        data: [
          { value: taskRate.value, name: '已完成' },
          { value: Math.max(0, 100 - taskRate.value), name: '待完成', itemStyle: { color: '#e8f0f8' }, tooltip: { show: false } },
        ],
      },
    ],
  })
}

function resizeTaskCompletionChart() {
  taskCompletionChart?.resize()
}

watch([taskRate, taskSuccessRate], () => { void nextTick(renderTaskCompletionChart) })

onMounted(async () => {
  await loadOverview()
  await nextTick()
  renderTaskCompletionChart()
  window.addEventListener('resize', resizeTaskCompletionChart)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeTaskCompletionChart)
  taskCompletionChart?.dispose()
  taskCompletionChart = null
})
</script>

<template>
  <section class="ops-dashboard-page">
    <section class="ops-hero">
      <div>
        <span>平台运营驾驶舱</span>
        <h2>任务运行、客户服务、接口成本一屏掌控</h2>
        <p>运营总览只展示平台内部需要处理的真实运行状态，不混入客户侧分析页面。</p>
      </div>
      <button class="ops-refresh" :disabled="loading" @click="loadOverview">
        <RefreshCw :class="{ spinning: loading }" />
        {{ loading ? '刷新中' : '刷新数据' }}
      </button>
    </section>

    <div v-if="errorText" class="ops-error">{{ errorText }}</div>

    <section class="ops-kpi-grid">
      <article v-for="item in kpiCards" :key="item.label" :class="['ops-kpi-card', `tone-${item.tone}`]">
        <div><component :is="item.icon" /></div>
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.note }}</small>
      </article>
    </section>

    <section class="ops-first-grid">
      <article class="panel ops-trend-card">
        <div class="panel-head">
          <div><h2>任务完成趋势</h2><p>今日完成率与接口成功率</p></div>
          <span>{{ taskRate }}%</span>
        </div>
        <div class="ops-progress-ring">
          <div ref="taskCompletionChartRef" class="ops-progress-echart"></div>
          <ul>
            <li><i></i>今日任务 {{ overview?.kpis.today_tasks || 0 }}</li>
            <li><i></i>已完成 {{ overview?.kpis.today_completed_tasks || 0 }}</li>
            <li><i></i>异常任务 {{ overview?.kpis.today_failed_tasks || 0 }}</li>
            <li><i></i>成功率 {{ taskSuccessRate }}%</li>
          </ul>
        </div>
      </article>

      <article class="panel ops-alert-card">
        <div class="panel-head">
          <div><h2>异常预警</h2><p>需要运营优先确认的事项</p></div>
          <AlertTriangle />
        </div>
        <div class="ops-alert-list">
          <div v-for="item in overview?.alerts || []" :key="item.title" :class="item.level">
            <span>{{ item.title }}</span>
            <b>{{ item.value }}</b>
          </div>
          <div v-if="!overview?.alerts?.length" class="mini-empty">暂无异常预警。</div>
        </div>
      </article>

      <article class="panel ops-todo-card">
        <div class="panel-head">
          <div><h2>待办事项</h2><p>续费、失败任务和同步事项</p></div>
          <Zap />
        </div>
        <div class="ops-todo-list">
          <button v-for="item in overview?.todo_items || []" :key="item.type" @click="props.navigateTo(todoTarget(item.type))">
            <span>{{ item.title }}</span>
            <b>{{ item.count }}</b>
            <ArrowRight />
          </button>
          <div v-if="!overview?.todo_items?.length" class="mini-empty compact-empty">今日暂无待处理事项。</div>
        </div>
      </article>
    </section>

    <section class="ops-second-grid">
      <article class="panel">
        <div class="panel-head"><div><h2>客户服务状态</h2><p>服务中、未开始、停服和到期客户分布</p></div><span>客户生命周期</span></div>
        <div class="ops-service-grid">
          <div v-for="row in serviceRows" :key="row.label" :class="row.tone">
            <span>{{ row.label }}</span>
            <b>{{ row.value }}</b>
          </div>
        </div>
        <div class="ops-expire-list">
          <b>即将到期客户</b>
          <p v-for="tenant in overview?.expiring_tenants || []" :key="tenant.id">{{ tenant.name }} <span>{{ tenant.days_left }} 天后到期</span></p>
          <p v-if="!overview?.expiring_tenants?.length">暂无 30 天内到期客户</p>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h2>模型平台运行情况</h2><p>按平台统计任务量、成功率和费用</p></div><Activity /></div>
        <div class="ops-platform-list">
          <div v-for="item in platformStats" :key="item.platform">
            <b>{{ props.platformLabelMap[item.platform] || item.platform }}</b>
            <span>已返回 {{ item.completed }} 条 · 成功率 {{ item.success_rate }}%</span>
            <i><em :style="{ width: `${Math.min(100, item.success_rate)}%` }"></em></i>
            <small>失败 {{ item.failed }} · 费用 {{ item.cost }}</small>
          </div>
          <div v-if="!platformStats.length" class="mini-empty">暂无平台运行数据。</div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h2>费用额度</h2><p>账户与 DeepSeek 余额、接口消耗与预计月消耗</p></div><WalletCards /></div>
        <div class="ops-quota-grid">
          <div v-for="row in quotaRows" :key="row.label" :class="{ 'is-highlight': row.highlight }">
            <span>{{ row.label }}</span>
            <b>{{ row.value }}</b>
            <small v-if="row.note">{{ row.note }}</small>
          </div>
        </div>
        <p v-if="(molizhishuBalance ?? overview?.molizhishu_balance)?.error" class="ops-balance-error">{{ (molizhishuBalance ?? overview?.molizhishu_balance)?.error }}</p>
        <p v-if="(deepseekBalance ?? overview?.deepseek_balance)?.error" class="ops-balance-error">{{ (deepseekBalance ?? overview?.deepseek_balance)?.error }}</p>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h2>费用消耗排行</h2><p>按企业与售前诊断汇总接口消耗</p></div><WalletCards /></div>
        <div class="ops-cost-list">
          <div v-for="(item, index) in overview?.cost_ranking || []" :key="`${item.tenant_id ?? 'lead'}-${item.lead_diagnosis_id ?? index}`">
            <i>{{ index + 1 }}</i>
            <span>{{ item.tenant_name }}</span>
            <b>{{ item.cost }}</b>
          </div>
          <div v-if="!overview?.cost_ranking?.length" class="mini-empty">暂无费用数据。</div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h2>最近任务队列</h2><p>最新提交和同步状态</p></div><BarChart3 /></div>
        <div class="ops-task-list">
          <div v-for="task in overview?.recent_tasks || []" :key="task.task_id">
            <b>{{ task.tenant_name }}</b>
            <span>{{ task.monitor_keywords || '未填监测词' }}</span>
            <em>{{ props.monitorStatusLabelMap[task.status] || task.status }} · {{ task.completed_items }}/{{ task.total_items }}</em>
          </div>
          <div v-if="!overview?.recent_tasks?.length" class="mini-empty">暂无最近任务。</div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h2>客户数据概况</h2><p>企业、任务与信源数据总览</p></div><FileBarChart /></div>
        <div class="ops-customer-data-grid">
          <div v-for="row in customerDataRows" :key="row.label">
            <span>{{ row.label }}</span>
            <b>{{ row.value }}</b>
          </div>
        </div>
      </article>
    </section>

    <section class="ops-third-grid">
      <article class="panel">
        <div class="panel-head"><div><h2>最近操作日志</h2><p>平台内部关键配置变更</p></div><Database /></div>
        <div class="ops-log-list">
          <div v-for="log in overview?.operation_logs || []" :key="log.id">
            <span>{{ log.created_at }}</span>
            <b>{{ cleanDashboardLog(log.operator_name, '历史日志') }}</b>
            <em>{{ cleanDashboardLog(log.action_type, '编码异常') }}</em>
            <p>{{ cleanDashboardLog(log.description) }}</p>
          </div>
          <div v-if="!overview?.operation_logs?.length" class="mini-empty">暂无操作日志。</div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h2>快捷操作</h2><p>常用运营入口</p></div><Settings /></div>
        <div class="ops-shortcuts">
          <button @click="props.navigateTo('platform.audit')">企业管理</button>
          <button @click="props.navigateTo('platform.users.create')">新增用户</button>
          <button @click="props.navigateTo('platform.alerts')">查看任务</button>
          <button @click="props.navigateTo('platform.logs')">操作日志</button>
        </div>
      </article>

      <article class="panel">
        <div class="panel-head"><div><h2>系统健康状态</h2><p>服务、数据库、调度和同步</p></div><Gauge /></div>
        <div class="ops-health-list">
          <div v-for="item in overview?.system_health || []" :key="item.name">
            <i :class="{ warn: item.status !== '正常' }"></i>
            <span>{{ item.name }}</span>
            <b>{{ item.status }}</b>
            <small>{{ item.detail }}</small>
          </div>
        </div>
      </article>
    </section>
  </section>
</template>
