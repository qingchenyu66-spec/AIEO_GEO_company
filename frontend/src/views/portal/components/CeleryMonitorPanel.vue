<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Activity, AlertTriangle, Clock3, Gauge, ListTodo, RefreshCw, Server, Workflow } from '@lucide/vue'
import { getCeleryMonitor, type CeleryMonitorData } from '../../../services/platforms'
import { extractErrorDetail } from '../../../utils/requestError'

const props = withDefaults(defineProps<{ autoRefresh?: boolean; refreshSeconds?: number }>(), {
  autoRefresh: true,
  refreshSeconds: 30,
})

const data = ref<CeleryMonitorData | null>(null)
const loading = ref(false)
const errorText = ref('')
let timer: number | undefined
let refreshDelayMs = props.refreshSeconds * 1000
let loadInFlight = false

function scheduleNextRefresh() {
  if (timer) window.clearTimeout(timer)
  if (!props.autoRefresh) return
  timer = window.setTimeout(() => {
    void loadMonitor().finally(scheduleNextRefresh)
  }, refreshDelayMs)
}

const checkedAtText = computed(() => {
  const raw = data.value?.checked_at
  if (!raw) return '尚未刷新'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('zh-CN', { hour12: false })
})

const workerSummary = computed(() => {
  const workers = data.value?.workers
  if (!workers) return '暂无数据'
  return `${workers.status} · ${workers.online_count} 个进程 · 执行中 ${workers.active_tasks} · 等待执行 ${workers.reserved_tasks}`
})

const runtimeTasks = computed(() => {
  const active = data.value?.runtime_tasks?.active || []
  const reserved = data.value?.runtime_tasks?.reserved || []
  return [...active, ...reserved]
})

const pendingSyncDetails = computed(() => data.value?.pending_sync_details || [])
const syncLive = computed(() => data.value?.sync_live || null)
const expandedBeatRows = ref<Record<string, boolean>>({})

function platformStatusClass(item: { pending?: number; processing?: number; failed?: number }) {
  if ((item.failed || 0) > 0) return 'is-critical'
  if ((item.pending || 0) > 0) return 'is-warning'
  if ((item.processing || 0) > 0) return 'is-active'
  return 'is-normal'
}

function platformStatusLabel(item: { completed?: number; pending?: number; processing?: number; failed?: number; total?: number }) {
  if ((item.failed || 0) > 0) return `失败 ${item.failed}`
  if ((item.pending || 0) > 0) return `排队 ${item.pending}`
  if ((item.processing || 0) > 0) return `执行 ${item.processing}`
  return `完成 ${item.completed || 0}/${item.total || 0}`
}

function taskStatusClass(status: string) {
  if (['completed'].includes(status)) return 'is-normal'
  if (['failed', 'stopped'].includes(status)) return 'is-critical'
  if (['partial_completed'].includes(status)) return 'is-warning'
  return 'is-active'
}

function toggleBeatRow(key: string) {
  expandedBeatRows.value[key] = !expandedBeatRows.value[key]
}

function beatRowKey(item: { task_key?: string; checked_at?: string }, index: number) {
  return `${item.task_key || 'beat'}-${item.checked_at || index}`
}

function formatTaskTime(raw?: string | null) {
  if (!raw) return '—'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatBeatTime(raw?: string) {
  if (!raw) return '—'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function beatStatusClass(status: string) {
  if (status === 'ok') return 'is-normal'
  if (status === 'locked') return 'is-warning'
  return 'is-critical'
}

async function loadMonitor() {
  if (loadInFlight || document.visibilityState === 'hidden') return
  loadInFlight = true
  loading.value = true
  errorText.value = ''
  try {
    data.value = await getCeleryMonitor()
    refreshDelayMs = props.refreshSeconds * 1000
  } catch (error: unknown) {
    const detail = extractErrorDetail(error)
    errorText.value = detail.includes('Not Found') || detail.includes('404')
      ? '监控接口未就绪，请重启后端服务后再刷新。'
      : detail.includes('503') || detail.includes('暂时不可用')
        ? '调度监控暂不可用，请确认 Celery Worker 与 Redis 已启动。'
        : detail || '监控加载失败，将稍后自动重试。'
    refreshDelayMs = Math.min(120_000, Math.max(refreshDelayMs * 2, props.refreshSeconds * 2000))
  } finally {
    loading.value = false
    loadInFlight = false
  }
}

function statusClass(level: string) {
  if (level === 'critical') return 'is-critical'
  if (level === 'warning') return 'is-warning'
  return 'is-normal'
}

onMounted(() => {
  void loadMonitor().finally(scheduleNextRefresh)
})

onUnmounted(() => {
  if (timer) window.clearTimeout(timer)
})
</script>

<template>
  <article class="panel celery-monitor-panel">
    <div class="panel-head">
      <div>
        <h2>调度运行监控</h2>
        <p>任务调度与队列状态 · 最近刷新 {{ checkedAtText }}</p>
      </div>
      <div class="celery-monitor-actions">
        <button class="ops-refresh compact" :disabled="loading" @click="loadMonitor">
          <RefreshCw :class="{ spinning: loading }" />
          {{ loading ? '刷新中' : '刷新' }}
        </button>
      </div>
    </div>

    <div v-if="errorText" class="ops-error">{{ errorText }}</div>

    <div v-if="data?.alerts?.length" class="celery-alert-list">
      <div v-for="(alert, index) in data.alerts" :key="`${alert.queue}-${index}`" :class="['celery-alert-item', statusClass(alert.level)]">
        <AlertTriangle />
        <div>
          <strong>{{ alert.title }}</strong>
          <p>{{ alert.message }}</p>
        </div>
      </div>
    </div>

    <div v-if="data?.ops_insights" class="celery-insights-grid">
      <section class="celery-insight-card">
        <Gauge />
        <div>
          <span>调度服务</span>
          <strong>{{ data.ops_insights.scheduler_status }}</strong>
          <small>提交与同步进程需同时在线</small>
        </div>
      </section>
      <section class="celery-insight-card">
        <Workflow />
        <div>
          <span>待同步监测任务</span>
          <strong>{{ data.ops_insights.pending_sync_tasks }}</strong>
          <small>已提交模力、结果尚未全部拉回</small>
        </div>
      </section>
      <section class="celery-insight-card">
        <Clock3 />
        <div>
          <span>今日调度入队</span>
          <strong>{{ data.ops_insights.today_enqueued_tasks }}</strong>
          <small>今日扫描 {{ data.ops_insights.today_scan_count }} 次</small>
        </div>
      </section>
      <section class="celery-insight-card">
        <Activity />
        <div>
          <span>最近到点扫描</span>
          <strong>{{ data.ops_insights.last_due_scan?.summary || '暂无记录' }}</strong>
          <small>{{ data.ops_insights.last_due_scan?.status_label || 'Beat 启动后会自动记录' }}</small>
        </div>
      </section>
    </div>

    <section v-if="syncLive" class="celery-sync-live-banner">
      <Activity />
      <div>
        <strong>正在同步</strong>
        <p>
          {{ syncLive.tenant_name || `企业 #${syncLive.tenant_id}` }}
          · {{ syncLive.monitor_keywords || '监测任务' }}
          · 进度 {{ syncLive.progress_text }}
        </p>
        <small v-if="syncLive.pending_platforms?.length">待完成平台：{{ syncLive.pending_platforms.join('、') }}</small>
        <small v-if="syncLive.prompts_preview">问题：{{ syncLive.prompts_preview }}</small>
      </div>
    </section>

    <section class="celery-runtime-section">
      <div class="celery-section-head">
        <ListTodo />
        <div>
          <h3>待同步监测明细</h3>
          <p>已提交模力、尚未全部拉回的主任务（{{ pendingSyncDetails.length }} 条，含平台与问题进度）</p>
        </div>
      </div>
      <div v-if="pendingSyncDetails.length" class="celery-sync-detail-list">
        <article v-for="item in pendingSyncDetails" :key="item.task_id" class="celery-sync-detail-card">
          <div class="celery-sync-detail-head">
            <div>
              <strong>{{ item.tenant_name || `企业 #${item.tenant_id}` }}</strong>
              <span>{{ item.monitor_keywords || item.keyword_group || '—' }}</span>
            </div>
            <div class="celery-sync-detail-meta">
              <em :class="taskStatusClass(item.status)">{{ item.status }}</em>
              <small>{{ item.schedule_label || item.task_id_short }}</small>
            </div>
          </div>
          <div class="celery-sync-detail-grid">
            <div>
              <label>进度</label>
              <strong>{{ item.progress_text }}</strong>
              <small>失败 {{ item.failed_items || 0 }}</small>
            </div>
            <div>
              <label>问题 ({{ item.prompt_count }})</label>
              <p>{{ item.prompts_preview || '—' }}</p>
            </div>
            <div>
              <label>待完成平台</label>
              <p>{{ item.pending_platforms?.length ? item.pending_platforms.join('、') : '无' }}</p>
            </div>
          </div>
          <ul v-if="item.platform_breakdown?.length" class="celery-platform-breakdown">
            <li v-for="platform in item.platform_breakdown" :key="`${item.task_id}-${platform.code}`">
              <span>{{ platform.name }}</span>
              <em :class="platformStatusClass(platform)">{{ platformStatusLabel(platform) }}</em>
              <small v-if="platform.pending_prompts?.length">排队问题：{{ platform.pending_prompts.join('；') }}</small>
            </li>
          </ul>
        </article>
      </div>
      <div v-else class="mini-empty">当前没有待同步的监测主任务。</div>
    </section>

    <div class="celery-monitor-grid">
      <section v-for="queue in data?.queues || []" :key="queue.key" class="celery-queue-card">
        <div class="celery-queue-head">
          <Workflow />
          <div>
            <span>{{ queue.name }}</span>
            <strong>{{ queue.pending }}</strong>
          </div>
          <em :class="statusClass(queue.status_level)">{{ queue.status }}</em>
        </div>
        <div class="celery-queue-bar">
          <i :style="{ width: `${queue.usage_percent}%` }" :class="statusClass(queue.status_level)" />
        </div>
        <small>预警 {{ queue.warning_threshold }} · 严重 {{ queue.critical_threshold }} · 占用 {{ queue.usage_percent }}%</small>
      </section>

      <section class="celery-worker-card">
        <div class="celery-queue-head">
          <Server />
          <div>
            <span>调度进程</span>
            <strong>{{ data?.workers.online_count ?? 0 }}</strong>
          </div>
          <em :class="data?.workers.status === '在线' ? 'is-normal' : 'is-critical'">{{ data?.workers.status || '未知' }}</em>
        </div>
        <p class="celery-worker-summary">{{ workerSummary }}</p>
        <ul v-if="data?.workers.items?.length" class="celery-worker-list">
          <li v-for="worker in data.workers.items" :key="worker.name">
            <b>{{ worker.role }}</b>
            <span>{{ worker.name }}</span>
          </li>
        </ul>
        <div v-else class="mini-empty">暂无在线调度进程。</div>
      </section>

      <section class="celery-scheduler-card">
        <div class="celery-queue-head">
          <Activity />
          <div>
            <span>定时调度</span>
            <strong>计划任务</strong>
          </div>
        </div>
        <ul class="celery-scheduler-list">
          <li>{{ data?.scheduler.submit_scan }}</li>
          <li>{{ data?.scheduler.sync_scan }}</li>
          <li>{{ data?.scheduler.backlog_check }}</li>
        </ul>
      </section>
    </div>

    <section class="celery-runtime-section">
      <div class="celery-section-head">
        <ListTodo />
        <div>
          <h3>正在执行的任务</h3>
          <p>调度进程当前执行或排队中的任务（{{ runtimeTasks.length }} 条）</p>
        </div>
      </div>
      <div v-if="runtimeTasks.length" class="celery-runtime-table">
        <div class="celery-runtime-head">
          <span>状态</span>
          <span>任务</span>
          <span>说明</span>
          <span>进程</span>
          <span>开始时间</span>
        </div>
        <div v-for="(task, index) in runtimeTasks" :key="`${task.task_id || task.task_key}-${index}`" class="celery-runtime-row">
          <em :class="task.phase === 'active' ? 'is-active' : 'is-reserved'">{{ task.phase_label }}</em>
          <strong>{{ task.label }}</strong>
          <span>{{ task.detail }}</span>
          <span>{{ task.worker_role }}</span>
          <small>{{ formatTaskTime(task.started_at) }}</small>
        </div>
      </div>
      <div v-else class="mini-empty">当前没有正在执行的调度任务。</div>
    </section>

    <section class="celery-runtime-section">
      <div class="celery-section-head">
        <Clock3 />
        <div>
          <h3>最近调度扫描</h3>
          <p>到点计划扫描、待同步扫描与队列健康检查记录</p>
        </div>
      </div>
      <div v-if="data?.beat_history?.length" class="celery-beat-table">
        <div class="celery-runtime-head celery-beat-head">
          <span>时间</span>
          <span>扫描类型</span>
          <span>结果</span>
          <span>摘要</span>
        </div>
        <div v-for="(item, index) in data.beat_history" :key="beatRowKey(item, index)" class="celery-beat-block">
          <div class="celery-runtime-row celery-beat-row">
            <small>{{ formatBeatTime(item.checked_at) }}</small>
            <strong>{{ item.label }}</strong>
            <em :class="beatStatusClass(item.status)">{{ item.status_label }}</em>
            <span class="celery-beat-summary">
              {{ item.summary || '—' }}
              <button
                v-if="item.sync_details?.length"
                type="button"
                class="celery-beat-expand"
                @click="toggleBeatRow(beatRowKey(item, index))"
              >
                {{ expandedBeatRows[beatRowKey(item, index)] ? '收起明细' : `查看 ${item.sync_details.length} 条同步明细` }}
              </button>
            </span>
          </div>
          <div
            v-if="item.sync_details?.length && expandedBeatRows[beatRowKey(item, index)]"
            class="celery-sync-detail-list celery-beat-sync-details"
          >
            <article v-for="detail in item.sync_details" :key="detail.task_id" class="celery-sync-detail-card compact">
              <div class="celery-sync-detail-head">
                <div>
                  <strong>{{ detail.tenant_name || `企业 #${detail.tenant_id}` }}</strong>
                  <span>{{ detail.monitor_keywords || '—' }} · {{ detail.progress_text }}</span>
                </div>
              </div>
              <div class="celery-sync-detail-grid compact">
                <div>
                  <label>问题</label>
                  <p>{{ detail.prompts_preview || '—' }}</p>
                </div>
                <div>
                  <label>待完成平台</label>
                  <p>{{ detail.pending_platforms?.length ? detail.pending_platforms.join('、') : '已全部完成' }}</p>
                </div>
              </div>
              <ul v-if="detail.platform_breakdown?.length" class="celery-platform-breakdown compact">
                <li v-for="platform in detail.platform_breakdown" :key="`${detail.task_id}-${platform.code}`">
                  <span>{{ platform.name }}</span>
                  <em :class="platformStatusClass(platform)">{{ platformStatusLabel(platform) }}</em>
                </li>
              </ul>
            </article>
          </div>
        </div>
      </div>
      <div v-else class="mini-empty">暂无调度扫描记录。定时调度启动后会自动写入最近 15 条。</div>
    </section>

    <ul v-if="data?.tips?.length" class="celery-tip-list">
      <li v-for="tip in data.tips" :key="tip">{{ tip }}</li>
    </ul>
  </article>
</template>
