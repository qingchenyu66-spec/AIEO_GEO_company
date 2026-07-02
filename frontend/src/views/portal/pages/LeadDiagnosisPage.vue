<script setup lang="ts">
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  CheckCircle2,
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
import { useLeadDiagnosis } from '../composables/useLeadDiagnosis'
import '../../../styles/lead-diagnosis.css'

const {
  loading,
  saving,
  exporting,
  detailLoading,
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
  filteredRecords,
  statsSummary,
  kpis,
  diagnosisBlock,
  platformStats,
  highlights,
  promptTemplates,
  scheduleSlots,
  runStatusLabels,
  statusLabels,
  platformLabelMap,
  formatDateTime,
  filledPromptCount,
  scheduleTimeline,
  progressPercent,
  healthTone,
  selectRecord,
  openCreatePanel,
  closeCreatePanel,
  applyPromptTemplate,
  nextCreateStep,
  handleRefresh,
  handleForceRun,
  handleExport,
} = useLeadDiagnosis()

const workflowSteps = [
  { title: '录入客户画像', desc: '品牌、联系人、竞品与核心问题', icon: Target },
  { title: '三时段采集', desc: scheduleSlots.join(' / '), icon: TimerReset },
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
  return Number.isInteger(number) ? `#${number}` : `#${number.toFixed(1)}`
}

function listProgress(item: { completed_run_count: number; schedule_times: string[] }) {
  const total = item.schedule_times?.length || 3
  return Array.from({ length: total }, (_, index) => {
    if (index < item.completed_run_count) return 'done'
    if (index === item.completed_run_count && item.completed_run_count < total) return 'running'
    return ''
  })
}
</script>

<template>
  <section class="lead-workspace" :class="{ 'is-creating': showCreatePanel }">
    <div v-if="showCreatePanel" class="lead-create">
      <div class="lead-create-hero">
        <div>
          <span class="lead-eyebrow">售前诊断任务</span>
          <h2>创建一份可交付的潜客诊断</h2>
          <p>系统会在指定时段采集 AI 平台回答，自动沉淀健康分、平台表现、引用来源与诊断建议。</p>
        </div>
        <button type="button" class="lead-icon-btn" @click="closeCreatePanel">
          <ArrowLeft :size="17" /> 返回列表
        </button>
      </div>

      <div class="lead-step-bar">
        <span :class="{ active: createStep === 1 }"><b>01</b> 客户与品牌</span>
        <span :class="{ active: createStep === 2 }"><b>02</b> 检测问题</span>
      </div>

      <div v-if="createStep === 1" class="lead-form lead-form-card">
        <div class="lead-form-grid">
          <label class="lead-field lead-field-wide">
            <span>品牌名称 *</span>
            <input v-model="createForm.brand_name" placeholder="例如：北京艾迪亚控股集团有限公司" />
          </label>
          <label class="lead-field">
            <span>联系人</span>
            <input v-model="createForm.contact_name" placeholder="销售跟进对象" />
          </label>
          <label class="lead-field">
            <span>手机号</span>
            <input v-model="createForm.contact_phone" placeholder="内部备注，不对外展示" />
          </label>
          <label class="lead-field lead-field-wide">
            <span>主要竞品</span>
            <input v-model="createForm.competitors" placeholder="多个竞品用逗号分隔，例如：竞品A, 竞品B" />
          </label>
          <label class="lead-field lead-field-wide">
            <span>销售备注</span>
            <textarea v-model="createForm.contact_note" rows="3" placeholder="客户来源、行业背景、意向度、重点关注点" />
          </label>
        </div>
        <div class="lead-form-hint">
          <Lightbulb :size="16" />
          <span>提交后按 <b>{{ scheduleSlots.join(' / ') }}</b> 三个时段抓取，全平台数据汇总后可导出 PDF。</span>
        </div>
        <div class="lead-form-actions">
          <button type="button" class="lead-secondary-btn" @click="closeCreatePanel">取消</button>
          <button type="button" class="lead-primary-btn" @click="nextCreateStep">
            下一步 <ArrowRight :size="16" />
          </button>
        </div>
      </div>

      <div v-else class="lead-form lead-form-card">
        <div class="lead-prompt-stack">
          <div v-for="(tpl, index) in promptTemplates" :key="index" class="lead-prompt-row">
            <label class="lead-field lead-prompt-field">
              <span>问题 {{ index + 1 }}{{ index === 0 ? ' *' : '' }}</span>
              <input v-model="createForm.prompts[index]" :placeholder="tpl.value" />
            </label>
            <button type="button" class="lead-template-btn" @click="applyPromptTemplate(index)">
              {{ tpl.label }}
            </button>
          </div>
        </div>
        <label class="lead-check-row">
          <input v-model="createForm.start_immediately" type="checkbox" />
          <span>创建后立即启动首轮抓取，其余时段仍按计划执行</span>
        </label>
        <div class="lead-form-hint">
          <Lightbulb :size="16" />
          <span>已填写 <b>{{ filledPromptCount }}</b> / 5 个问题。建议覆盖推荐、排名、选购、竞品比较与可信度。</span>
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
          <input v-model="keywordFilter" placeholder="搜索品牌、联系人、手机号" />
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
            <p>{{ item.contact_name || '未填联系人' }} · {{ item.diagnosis_date }}</p>
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
                {{ detail?.contact_name || '未填联系人' }}
                <template v-if="detail?.contact_phone"> · {{ detail.contact_phone }}</template>
                · 诊断日期 {{ detail?.diagnosis_date }}
              </small>
            </div>
            <div class="lead-detail-actions">
              <button type="button" class="lead-secondary-btn small" :disabled="detailLoading" @click="handleRefresh">
                <RefreshCw :size="16" /> 刷新进度
              </button>
              <button v-if="canCreate && detail?.status !== 'ready'" type="button" class="lead-secondary-btn small" @click="handleForceRun">
                <Zap :size="16" /> 立即抓取
              </button>
              <button v-if="canExport && detail?.status === 'ready'" type="button" class="lead-primary-btn small" :disabled="exporting" @click="handleExport">
                <Download :size="16" /> {{ exporting ? '导出中...' : '下载 PDF' }}
              </button>
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
                <span>{{ detail.completed_run_count }}/{{ detail.schedule_times?.length || scheduleSlots.length }} 时段完成</span>
              </div>
            </div>

            <nav class="lead-tabs">
              <button type="button" :class="{ active: detailTab === 'progress' }" @click="detailTab = 'progress'">
                <Clock3 :size="14" /> 抓取进度
              </button>
              <button type="button" :class="{ active: detailTab === 'report' }" :disabled="detail.status !== 'ready'" @click="detailTab = 'report'">
                <FileText :size="14" /> 诊断结论
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
                <h3>三时段抓取计划</h3>
                <p>每个时段对全部启用平台和检测问题各跑一次，完成后自动汇总结论。</p>
              </div>
              <div class="lead-timeline">
                <article v-for="slot in scheduleTimeline" :key="slot.schedule_key" class="lead-slot" :class="slotClass(slot.state)">
                  <div class="lead-slot-index">
                    <CheckCircle2 v-if="slot.state === 'completed'" :size="20" />
                    <span v-else>{{ slot.index }}</span>
                  </div>
                  <div class="lead-slot-body">
                    <b>{{ slot.slot }} 时段</b>
                    <small v-if="slot.run">
                      {{ slot.run.prompt_count }} 问题 x {{ slot.run.platform_count }} 平台 · {{ runStatusLabels[slot.run.status] || slot.run.status }}
                    </small>
                    <small v-else>等待到点自动执行，或点击“立即抓取”。</small>
                  </div>
                  <span class="lead-badge" :class="slot.state === 'completed' ? 'ready' : slot.state === 'failed' ? 'failed' : 'collecting'">
                    {{ slot.run ? (runStatusLabels[slot.run.status] || slot.run.status) : '待执行' }}
                  </span>
                </article>
              </div>
            </section>

            <section v-else-if="detailTab === 'report'" class="lead-panel">
              <div class="lead-panel-title">
                <h3>诊断结论</h3>
                <p>用于售前沟通的摘要、优势、风险与优化建议。</p>
              </div>
              <div v-if="detail.status !== 'ready'" class="lead-form-hint">
                <Lightbulb :size="16" />
                <span>诊断尚未完成，请等待三时段抓取结束或刷新进度。</span>
              </div>
              <div v-else class="lead-report-block">
                <article>
                  <span>整体评估</span>
                  <p>{{ diagnosisBlock.sentiment_summary || '暂无摘要' }}</p>
                </article>
                <article v-if="highlights.length">
                  <span>核心发现</span>
                  <ul>
                    <li v-for="(line, index) in highlights" :key="index">{{ line }}</li>
                  </ul>
                </article>
                <article><span>优势亮点</span><p>{{ diagnosisBlock.strength_points || '-' }}</p></article>
                <article><span>待改善项</span><p>{{ diagnosisBlock.weakness_points || '-' }}</p></article>
                <article class="wide"><span>GEO 优化建议</span><p>{{ diagnosisBlock.recommendation || '-' }}</p></article>
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
                <p>售前诊断的输入范围和创建记录。</p>
              </div>
              <div class="lead-config-list">
                <div><strong>检测问题</strong><span>{{ (detail.prompts || []).join('；') }}</span></div>
                <div><strong>竞品</strong><span>{{ (detail.competitors || []).join('、') || '未填写' }}</span></div>
                <div><strong>抓取时段</strong><span>{{ (detail.schedule_times || scheduleSlots).join('、') }}</span></div>
                <div v-if="detail.contact_note"><strong>销售备注</strong><span>{{ detail.contact_note }}</span></div>
                <div><strong>创建时间</strong><span>{{ formatDateTime(detail.created_at) }}</span></div>
              </div>
            </section>
          </template>
        </template>
      </main>
    </template>
  </section>
</template>
