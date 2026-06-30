<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { AlertTriangle, ArrowRight, Award, CheckCircle2, ChevronDown, ChevronRight, Clock3, Hash, Megaphone, Minimize2, PlusCircle, RefreshCw, Search } from '@lucide/vue'
import { useWorkspaceEnter } from '../../../composables/useCountUp'
import { useWorkspaceDeckWheel } from '../../../composables/useWorkspaceDeckWheel'
import PlatformBadge from '../../../components/PlatformBadge.vue'
import WorkspaceCountUp from '../components/WorkspaceCountUp.vue'
import WorkspaceSparkline from '../components/WorkspaceSparkline.vue'
import { useCustomerWorkspace } from '../composables/useCustomerWorkspace'
import { WorkspaceFullscreenKey } from '../injectionKeys'

const {
  brief,
  loading,
  alertsExpanded,
  heroTone,
  statusBadge,
  statusSummary,
  primaryAction,
  visibleAlerts,
  hiddenAlertCount,
  loadBrief,
  navigateToMenu,
  openSnapshot,
  workspaceQuickLinks,
  formatDateTime,
  formatKpiDelta,
  kpiDeltaClass,
  formatPlatformDelta,
  platformDeltaClass,
  platformHighlightsSorted,
  platformMatrixSummary,
  platformAccentColor,
  platformLeaderRank,
  platformMentionBarWidth,
  unpurchasedPlatforms,
  showUnpurchasedDeck,
  kpiTrendValues,
  snapshotMetric,
  snapshotIntentClass,
  snapshotIntentLabel,
  platformLabelMap,
} = useCustomerWorkspace()

const { enterActive, enterGeneration } = useWorkspaceEnter(() => brief.value)
const workspaceFullscreen = inject(WorkspaceFullscreenKey)
const isFullscreen = computed(() => workspaceFullscreen?.isFullscreen.value ?? false)

async function toggleFullscreen() {
  await workspaceFullscreen?.toggle()
}

const displayName = computed(() => brief.value?.company_name || brief.value?.brand_name || '当前企业')
const roundComparison = computed(() => brief.value?.round_comparison)
const hasRoundDelta = computed(() => Boolean(roundComparison.value?.has_previous))
const mentionTrend = computed(() => kpiTrendValues(brief.value, 'mention_rate'))
const rankTrend = computed(() => kpiTrendValues(brief.value, 'avg_brand_rank'))
const top3Trend = computed(() => kpiTrendValues(brief.value, 'top3_rate'))
const showEmptyGuide = computed(() => heroTone.value === 'empty' && !loading.value)

const scheduleLine = computed(() => {
  const latest = brief.value?.latest_schedule
  if (!latest?.schedule_label) return '暂无已完成调度轮次'
  const previous = brief.value?.previous_schedule
  if (previous?.schedule_label && roundComparison.value?.has_previous) {
    return `${latest.schedule_label} · 对比 ${previous.schedule_label}`
  }
  return `${latest.schedule_label} · 已完成 ${latest.completed_subtasks} 条`
})

const emptyHint = computed(() => {
  if (brief.value?.recent_snapshots?.length) return ''
  return brief.value?.next_schedule_hint
    ? `暂无已完成检测结果，下次监测计划：${brief.value.next_schedule_hint}`
    : '暂无已完成检测结果，请等待定时监测任务返回。'
})

const heroClass = computed(() => ({
  'is-calm': heroTone.value === 'calm',
  'is-risk': heroTone.value === 'warn',
  'is-empty': heroTone.value === 'empty',
}))

function platformRowDelay(rowIndex: number) {
  return `${240 + rowIndex * 55}ms`
}

const scrollDeckRef = ref<HTMLElement | null>(null)

const deckPageIds = computed(() => {
  if (showEmptyGuide.value) return [] as string[]
  const ids = ['workspace-deck-hero']
  if (platformHighlightsSorted.value.length) ids.push('workspace-deck-platform')
  if (showUnpurchasedDeck.value) ids.push('workspace-deck-upsell')
  ids.push('workspace-deck-sources', 'workspace-deck-snapshots')
  return ids
})
useWorkspaceDeckWheel(scrollDeckRef, deckPageIds)
</script>

<template>
  <section
    ref="scrollDeckRef"
    class="customer-workspace-page workspace-scroll-deck"
    :class="{ 'is-fullscreen': isFullscreen }"
    tabindex="0"
  >
    <button
      v-if="isFullscreen"
      type="button"
      class="workspace-fullscreen-exit"
      @click="toggleFullscreen"
    >
      <Minimize2 />
      退出全屏
      <kbd>Esc</kbd>
    </button>
    <article id="workspace-deck-hero" class="workspace-deck-page workspace-cinematic-hero" :class="[heroClass, { 'hero-visible': enterActive || loading || !brief }]">
      <div class="workspace-hero-bg" aria-hidden="true">
        <span class="workspace-orb orb-a" />
        <span class="workspace-orb orb-b" />
        <span class="workspace-hero-grid" />
      </div>

      <div class="workspace-hero-body workspace-enter-stage" :class="{ 'is-active': enterActive }">
        <div class="workspace-brief-top workspace-enter" style="--enter-delay: 0ms">
          <div class="workspace-brief-intro">
            <span class="workspace-hero-kicker">GEO 智能监测 · 运营工作台</span>
            <div class="workspace-status-row">
              <h2>{{ displayName }}</h2>
              <span class="workspace-status-badge" :class="`tone-${statusBadge.tone}`">{{ statusBadge.label }}</span>
            </div>
            <p class="workspace-hero-subline">近 7 日监测简报 · {{ scheduleLine }}</p>
            <small v-if="brief?.next_schedule_hint">监测计划 {{ brief.next_schedule_hint }}</small>
          </div>

          <div v-if="brief" class="workspace-hero-spotlight workspace-enter" style="--enter-delay: 120ms">
            <span class="workspace-spotlight-label">推荐类露出率</span>
            <strong class="workspace-spotlight-value">
              <WorkspaceCountUp
                :value="brief.kpis.brand_mention_rate"
                :active="enterActive"
                :generation="enterGeneration"
                :decimals="1"
                :duration="1100"
              /><em>%</em>
            </strong>
            <WorkspaceSparkline
              :values="mentionTrend"
              :width="120"
              :height="36"
              tone="light"
              show-area
            />
          </div>

          <div class="workspace-brief-actions workspace-enter" style="--enter-delay: 80ms">
            <button
              v-if="primaryAction"
              type="button"
              class="workspace-primary-cta"
              @click="navigateToMenu(primaryAction.menu)"
            >
              {{ primaryAction.label }}
              <ChevronRight />
            </button>
            <button type="button" class="workspace-ghost-btn" :disabled="loading" @click="loadBrief">
              <RefreshCw :class="{ spinning: loading }" />
              刷新
            </button>
          </div>
        </div>

        <nav class="workspace-quick-strip" aria-label="快捷入口">
          <button
            v-for="(link, index) in workspaceQuickLinks"
            :key="link.code"
            type="button"
            class="workspace-quick-tile workspace-enter"
            :style="{ '--enter-delay': `${180 + index * 70}ms` }"
            @click="navigateToMenu(link.code)"
          >
            <span class="workspace-quick-tile-icon"><component :is="link.icon" /></span>
            <span class="workspace-quick-tile-copy">
              <b>{{ link.title }}</b>
              <small>{{ link.note }}</small>
            </span>
            <ArrowRight />
          </button>
        </nav>

        <div v-if="loading && !brief" class="workspace-brief-skeleton">
          <div v-for="n in 3" :key="n" />
        </div>
        <template v-else-if="brief">
          <template v-if="!showEmptyGuide">
          <div class="workspace-hero-main-panel">
          <p class="workspace-status-summary workspace-enter" :class="{ calm: heroTone === 'calm', warn: heroTone === 'warn', empty: heroTone === 'empty' }" style="--enter-delay: 260ms">
            <CheckCircle2 v-if="heroTone === 'calm'" />
            <AlertTriangle v-else-if="heroTone === 'warn'" />
            <Clock3 v-else />
            {{ statusSummary }}
          </p>
          <div class="workspace-kpi-row">
            <div class="workspace-kpi-card tone-blue workspace-enter" style="--enter-delay: 340ms">
              <div class="workspace-kpi-icon"><Megaphone /></div>
              <div class="workspace-kpi-card-top">
                <span>推荐类露出率</span>
                <WorkspaceSparkline :values="mentionTrend" tone="light" show-area />
              </div>
              <b>
                <WorkspaceCountUp
                  :value="brief.kpis.brand_mention_rate"
                  :active="enterActive"
                  :generation="enterGeneration"
                  :decimals="1"
                  :duration="1000"
                /><small>%</small>
              </b>
              <span class="workspace-kpi-note">{{ brief.kpis.ranking_sample_count }} 条排名类样本</span>
              <span
                v-if="hasRoundDelta && roundComparison?.mention_rate_delta != null"
                class="workspace-kpi-delta"
                :class="kpiDeltaClass(roundComparison?.mention_rate_delta)"
              >
                {{ formatKpiDelta(roundComparison?.mention_rate_delta, '%') }}
              </span>
            </div>
            <div class="workspace-kpi-card tone-cyan workspace-enter" style="--enter-delay: 420ms">
              <div class="workspace-kpi-icon"><Hash /></div>
              <div class="workspace-kpi-card-top">
                <span>平均推荐排名</span>
                <WorkspaceSparkline :values="rankTrend" lower-is-better tone="light" show-area stroke="#7de8ff" />
              </div>
              <b>
                <WorkspaceCountUp
                  :value="brief.kpis.avg_brand_rank"
                  :active="enterActive"
                  :generation="enterGeneration"
                  :decimals="1"
                  :duration="1000"
                />
              </b>
              <span class="workspace-kpi-note">越小越靠前</span>
              <span
                v-if="hasRoundDelta && roundComparison?.avg_brand_rank_delta != null"
                class="workspace-kpi-delta"
                :class="kpiDeltaClass(roundComparison?.avg_brand_rank_delta, true)"
              >
                {{ formatKpiDelta(roundComparison?.avg_brand_rank_delta, ' 位', true, 'rank') }}
              </span>
            </div>
            <div class="workspace-kpi-card tone-emerald workspace-enter" style="--enter-delay: 500ms">
              <div class="workspace-kpi-icon"><Award /></div>
              <div class="workspace-kpi-card-top">
                <span>Top3 占比</span>
                <WorkspaceSparkline :values="top3Trend" tone="light" show-area stroke="#6dffc8" />
              </div>
              <b>
                <WorkspaceCountUp
                  :value="brief.kpis.top3_rate ?? 0"
                  :active="enterActive"
                  :generation="enterGeneration"
                  :decimals="1"
                  :duration="900"
                /><small>%</small>
              </b>
              <span class="workspace-kpi-note">排名类 · 进入前三比例</span>
              <span
                v-if="hasRoundDelta && roundComparison?.top3_rate_delta != null"
                class="workspace-kpi-delta"
                :class="kpiDeltaClass(roundComparison?.top3_rate_delta)"
              >
                {{ formatKpiDelta(roundComparison?.top3_rate_delta, '%') }}
              </span>
            </div>
          </div>

          <div class="workspace-meta-strip workspace-enter" style="--enter-delay: 580ms">
            <div class="workspace-meta-item">
              <span>信源引用</span>
              <b>
                <WorkspaceCountUp
                  :value="brief.kpis.source_count"
                  :active="enterActive"
                  :generation="enterGeneration"
                  :duration="900"
                />
              </b>
              <small>近 7 日 AI 回答引用</small>
            </div>
            <div class="workspace-meta-item">
              <span>竞品监测</span>
              <b>
                <WorkspaceCountUp
                  :value="brief.kpis.competitor_count"
                  :active="enterActive"
                  :generation="enterGeneration"
                  :duration="900"
                />
              </b>
              <small>已配置竞品数量</small>
            </div>
          </div>

          <div v-if="visibleAlerts.length" class="workspace-alert-center workspace-enter" style="--enter-delay: 640ms">
            <div
              v-for="alert in visibleAlerts"
              :key="alert.message"
              class="workspace-alert"
              :class="alert.level"
            >
              <AlertTriangle v-if="alert.level === 'warn'" />
              <Clock3 v-else />
              <span>{{ alert.message }}</span>
            </div>
            <button
              v-if="hiddenAlertCount > 0"
              type="button"
              class="workspace-alert-toggle"
              @click="alertsExpanded = true"
            >
              展开其余 {{ hiddenAlertCount }} 条提醒
              <ChevronDown />
            </button>
            <button
              v-else-if="alertsExpanded && (brief.alerts.length > 2)"
              type="button"
              class="workspace-alert-toggle"
              @click="alertsExpanded = false"
            >
              收起提醒
              <ChevronDown class="is-flipped" />
            </button>
          </div>
          </div>
          </template>

          <p v-else class="workspace-status-summary workspace-enter" :class="{ calm: heroTone === 'calm', warn: heroTone === 'warn', empty: heroTone === 'empty' }" style="--enter-delay: 260ms">
            <CheckCircle2 v-if="heroTone === 'calm'" />
            <AlertTriangle v-else-if="heroTone === 'warn'" />
            <Clock3 v-else />
            {{ statusSummary }}
          </p>

          <section v-if="showEmptyGuide" class="workspace-empty-guide workspace-enter-stage" :class="{ 'is-active': enterActive }">
            <div class="workspace-empty-guide-glow workspace-enter" style="--enter-delay: 0ms" aria-hidden="true" />
            <div class="workspace-empty-guide-icon workspace-enter" style="--enter-delay: 80ms">
              <Clock3 />
            </div>
            <div class="workspace-empty-guide-copy workspace-enter" style="--enter-delay: 160ms">
              <h3>等待首次监测结果</h3>
              <p>{{ emptyHint }}</p>
              <ul>
                <li>系统会按监测计划自动发起检测，无需手动提交</li>
                <li>结果返回后，这里会展示 KPI、平台表现与检测快照</li>
                <li>可先查看实时检测页了解任务结构，或维护品牌/竞品配置</li>
              </ul>
            </div>
            <div class="workspace-empty-guide-actions workspace-enter" style="--enter-delay: 240ms">
              <button type="button" class="primary-btn small-btn" @click="navigateToMenu('customer.realtime')">
                <Search />
                查看实时检测
              </button>
            </div>
          </section>
        </template>
      </div>
    </article>

    <section
      v-if="platformHighlightsSorted.length"
      id="workspace-deck-platform"
      class="workspace-deck-page workspace-platform-deck-page workspace-enter-stage"
      :class="{ 'is-active': enterActive }"
    >
      <div class="workspace-glass-panel workspace-platform-panel workspace-platform-deck-inner">
        <div class="workspace-section-head workspace-enter" style="--enter-delay: 120ms">
          <div>
            <span class="workspace-section-eyebrow">Platform Matrix</span>
            <h2>已购平台表现</h2>
            <p>最新调度轮次 · 按露出率排序 · 共 {{ platformHighlightsSorted.length }} 个平台</p>
          </div>
          <div class="workspace-platform-deck-actions">
            <button type="button" class="ghost-link-btn" @click="navigateToMenu('customer.realtime')">
              查看实时检测
              <ChevronRight />
            </button>
          </div>
        </div>

        <div
          v-if="platformMatrixSummary.activeCount"
          class="workspace-platform-summary workspace-enter"
          style="--enter-delay: 160ms"
        >
          <div class="workspace-platform-summary-item">
            <span>有效平台</span>
            <strong>{{ platformMatrixSummary.activeCount }}<em>/{{ platformMatrixSummary.total }}</em></strong>
          </div>
          <div class="workspace-platform-summary-item">
            <span>平均露出</span>
            <strong>
              <WorkspaceCountUp
                :value="platformMatrixSummary.avgMention"
                :active="enterActive"
                :generation="enterGeneration"
                :decimals="1"
                :duration="700"
              />%
            </strong>
          </div>
          <div v-if="platformMatrixSummary.leader" class="workspace-platform-summary-item is-leader">
            <span>领跑平台</span>
            <strong>
              {{ platformLabelMap[platformMatrixSummary.leader.platform] || platformMatrixSummary.leader.platform }}
              <em>
                <WorkspaceCountUp
                  :value="platformMatrixSummary.leader.mention_rate"
                  :active="enterActive"
                  :generation="enterGeneration"
                  :decimals="1"
                  :duration="700"
                />%
              </em>
            </strong>
          </div>
          <div v-if="platformMatrixSummary.emptyCount" class="workspace-platform-summary-item is-muted">
            <span>待返回</span>
            <strong>{{ platformMatrixSummary.emptyCount }} 个</strong>
          </div>
        </div>

        <div class="workspace-platform-matrix workspace-platform-matrix-scroll workspace-enter" style="--enter-delay: 200ms">
          <div class="workspace-platform-matrix-head" aria-hidden="true">
            <span>平台</span>
            <span>品牌露出率</span>
            <span>平均排名</span>
            <span v-if="hasRoundDelta">较上一轮</span>
            <span />
          </div>
          <button
            v-for="(row, index) in platformHighlightsSorted"
            :key="row.platform"
            type="button"
            class="workspace-platform-matrix-row workspace-enter"
            :class="{
              'is-empty': row.sample_count === 0,
              'is-leader': row.platform === platformMatrixSummary.leader?.platform,
            }"
            :style="{
              '--accent': platformAccentColor(row.platform),
              '--enter-delay': platformRowDelay(index),
            }"
            @click="navigateToMenu('customer.realtime')"
          >
            <div class="workspace-platform-matrix-identity">
              <span class="workspace-platform-avatar">
                <PlatformBadge :code="row.platform" size="md" icon-only />
              </span>
              <div>
                <b>
                  {{ platformLabelMap[row.platform] || row.platform }}
                  <i v-if="platformLeaderRank(row, platformHighlightsSorted) === 1" class="workspace-platform-leader-tag">领跑</i>
                  <i
                    v-else-if="platformLeaderRank(row, platformHighlightsSorted) > 1"
                    class="workspace-platform-rank-tag"
                  >#{{ platformLeaderRank(row, platformHighlightsSorted) }}</i>
                </b>
                <small v-if="row.sample_count > 0">{{ row.sample_count }} 条样本</small>
                <small v-else class="is-muted">本轮暂无返回</small>
              </div>
            </div>

            <div class="workspace-platform-matrix-mention">
              <div class="workspace-platform-mention-track" aria-hidden="true">
                <i :style="{ width: `${platformMentionBarWidth(row.mention_rate)}%` }" />
              </div>
              <strong v-if="row.sample_count > 0">
                <WorkspaceCountUp
                  :value="row.mention_rate"
                  :active="enterActive"
                  :generation="enterGeneration"
                  :decimals="1"
                  :duration="800"
                />%
              </strong>
              <span v-else class="workspace-platform-na">—</span>
            </div>

            <div class="workspace-platform-matrix-rank">
              <template v-if="row.avg_rank != null && row.sample_count > 0">
                <strong>
                  <WorkspaceCountUp
                    :value="row.avg_rank"
                    :active="enterActive"
                    :generation="enterGeneration"
                    :decimals="1"
                    :duration="800"
                  />
                </strong>
                <small>位</small>
              </template>
              <span v-else class="workspace-platform-na">—</span>
            </div>

            <div v-if="hasRoundDelta" class="workspace-platform-matrix-delta">
              <template v-if="row.mention_rate_delta != null || row.avg_rank_delta != null">
                <span v-if="row.mention_rate_delta != null" :class="platformDeltaClass(row.mention_rate_delta)">
                  露出 {{ formatPlatformDelta(row.mention_rate_delta, '%') }}
                </span>
                <span v-if="row.avg_rank_delta != null" :class="platformDeltaClass(row.avg_rank_delta, true)">
                  排名 {{ formatPlatformDelta(row.avg_rank_delta, ' 位', true) }}
                </span>
              </template>
              <span v-else class="workspace-platform-na">—</span>
            </div>

            <ChevronRight class="workspace-platform-matrix-arrow" aria-hidden="true" />
          </button>
        </div>

        <p v-if="showUnpurchasedDeck" class="workspace-deck-inline-cue">
          继续向下滚动 · 查看可扩容平台
        </p>
      </div>
    </section>

    <section
      v-if="showUnpurchasedDeck"
      id="workspace-deck-upsell"
      class="workspace-deck-page workspace-upsell-deck-page workspace-enter-stage"
      :class="{ 'is-active': enterActive }"
    >
      <div class="workspace-glass-panel workspace-upsell-panel workspace-enter" style="--enter-delay: 120ms">
        <div class="workspace-section-head">
          <div>
            <span class="workspace-section-eyebrow">Expand Coverage</span>
            <h2>可扩容 AI 平台</h2>
            <p>
              当前已购 {{ brief?.purchased_platforms?.length || 0 }} 个平台 · 还有 {{ unpurchasedPlatforms.length }} 个可开通
            </p>
          </div>
          <span class="workspace-section-chip is-upsell">
            <PlusCircle />
            联系运营扩容
          </span>
        </div>

        <div class="workspace-unpurchased-grid">
          <div
            v-for="platform in unpurchasedPlatforms"
            :key="platform.code"
            class="workspace-unpurchased-card"
            :style="{ '--accent': platformAccentColor(platform.code) }"
          >
            <span class="workspace-platform-avatar">
              <PlatformBadge :code="platform.code" size="md" icon-only />
            </span>
            <div>
              <b>{{ platform.name }}</b>
              <small>尚未纳入监测</small>
            </div>
            <span class="workspace-unpurchased-tag">未开通</span>
          </div>
        </div>

        <div class="workspace-upsell-foot">
          <p>如需增加监测平台，请联系您的 GEO 运营顾问扩容套餐，开通后即可在本页查看各平台表现。</p>
          <div class="workspace-upsell-purchased">
            <span>已购平台</span>
            <em>
              {{ (brief?.purchased_platforms || []).map(code => platformLabelMap[code] || code).join('、') || '暂无' }}
            </em>
          </div>
        </div>
      </div>
    </section>

    <section
      v-if="!showEmptyGuide"
      id="workspace-deck-sources"
      class="workspace-deck-page workspace-insight-deck-page workspace-enter-stage"
      :class="{ 'is-active': enterActive }"
    >
      <article class="workspace-glass-panel workspace-source-panel workspace-source-deck-inner workspace-enter" style="--enter-delay: 180ms">
        <div class="workspace-section-head compact">
          <div>
            <span class="workspace-section-eyebrow">Top Sources</span>
            <h2>高频信源</h2>
            <p>近 7 日 AI 回答引用 Top 5</p>
          </div>
          <button type="button" class="ghost-link-btn" @click="navigateToMenu('customer.sources')">
            查看全部信源
            <ChevronRight />
          </button>
        </div>
        <div v-if="brief?.top_sources?.length" class="workspace-source-list">
          <a
            v-for="(source, index) in brief.top_sources"
            :key="source.url"
            :href="source.url"
            target="_blank"
            rel="noopener"
          >
            <span class="workspace-source-rank">{{ index + 1 }}</span>
            <div class="workspace-source-copy">
              <b>{{ source.title }}</b>
              <span class="workspace-source-platforms">{{ (source.platforms || []).map(code => platformLabelMap[code] || code).join('、') }}</span>
            </div>
            <span class="workspace-source-count">
              <WorkspaceCountUp
                :value="source.count"
                :active="enterActive"
                :generation="enterGeneration"
                :duration="700"
              /> 次
            </span>
          </a>
        </div>
        <div v-else class="mini-empty">暂无信源数据，监测返回后会自动展示。</div>
      </article>
    </section>

    <section
      v-if="!showEmptyGuide"
      id="workspace-deck-snapshots"
      class="workspace-deck-page workspace-insight-deck-page workspace-enter-stage"
      :class="{ 'is-active': enterActive }"
    >
      <article class="workspace-glass-panel workspace-snapshot-panel workspace-snapshot-deck-inner workspace-enter" style="--enter-delay: 280ms">
        <div class="workspace-section-head compact">
          <div>
            <span class="workspace-section-eyebrow">Live Snapshots</span>
            <h2>最近检测快照</h2>
            <p>点击条目进入实时检测查看详情</p>
          </div>
          <button type="button" class="ghost-link-btn" @click="navigateToMenu('customer.realtime')">
            进入实时检测
            <ChevronRight />
          </button>
        </div>
        <div v-if="loading" class="mini-empty">加载中…</div>
        <div v-else-if="brief?.recent_snapshots?.length" class="workspace-snapshot-list">
          <button
            v-for="(item, index) in brief.recent_snapshots"
            :key="item.subtask_id"
            type="button"
            class="workspace-snapshot-card workspace-enter"
            :class="{ negative: item.sentiment === '负面' }"
            :style="{ '--enter-delay': `${360 + index * 60}ms` }"
            @click="openSnapshot(item)"
          >
            <div class="workspace-snapshot-head">
              <span class="workspace-intent-pill" :class="snapshotIntentClass(item)">{{ snapshotIntentLabel(item) }}</span>
              <span>{{ platformLabelMap[item.platform] || item.platform }}</span>
              <span>{{ item.schedule_label || formatDateTime(item.updated_at) }}</span>
            </div>
            <h3>{{ item.prompt }}</h3>
            <p>{{ item.answer_excerpt || '暂无摘要' }}</p>
            <div class="workspace-snapshot-foot">
              <span>{{ snapshotMetric(item) }}</span>
              <span class="workspace-snapshot-link">查看详情 <ChevronRight /></span>
            </div>
          </button>
        </div>
        <div v-else class="mini-empty workspace-empty-hint">{{ emptyHint }}</div>
      </article>
    </section>
  </section>
</template>
