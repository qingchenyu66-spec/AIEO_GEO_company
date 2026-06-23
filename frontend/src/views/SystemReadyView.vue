<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Activity, ArrowRight, BarChart3, Building2, ClipboardCheck, Code2, Database,
  FileBarChart, Gauge, Layers3, RefreshCw, Search, Server, Settings, ShieldCheck
} from '@lucide/vue'
import { getHealth, type HealthData } from '../services/system'

const health = ref<HealthData | null>(null)
const loading = ref(false)
const error = ref('')

const navItems = [
  [Gauge, '项目初始化'], [BarChart3, '运营工作台'], [Building2, '品牌资产'],
  [Search, '实时检测'], [Layers3, '批量监控'], [Activity, 'GEO监测'],
  [ClipboardCheck, '品牌诊断'], [FileBarChart, '报告中心'], [Settings, '系统管理'],
]

const nextModules = [
  [ShieldCheck, '登录与权限', '租户隔离、菜单权限、数据范围'],
  [Building2, '企业与品牌', '企业档案、品牌词与竞品配置'],
  [Search, '检测任务', '接入模力指数 API 并保存结果'],
  [FileBarChart, '监测报告', '图表、明细、快照与导出'],
]

const apiReady = computed(() => health.value?.api === 'ready')
const dbReady = computed(() => health.value?.database === 'ready')

async function refreshHealth() {
  loading.value = true
  error.value = ''
  try {
    health.value = await getHealth()
  } catch (e) {
    error.value = '后端尚未启动或接口连接失败'
  } finally {
    loading.value = false
  }
}

onMounted(refreshHealth)
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">G</div>
        <div><strong>GEO Monitor</strong><span>AI 平台推广监测系统</span></div>
      </div>
      <nav class="nav">
        <a v-for="([icon, label], index) in navItems" :key="label as string" href="#" class="nav-item" :class="{ active: index === 0 }" @click.prevent>
          <component :is="icon" class="nav-icon" /><span>{{ label }}</span>
        </a>
      </nav>
      <div class="sidebar-foot"><b>开发环境</b><span>前后端项目已独立，后续功能按模块逐步接入。</span></div>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div class="crumb">GEO Monitor / 项目初始化</div>
        <div class="top-actions"><span class="env-chip">本地开发环境</span><span class="env-chip">v0.1.0</span></div>
      </header>

      <main class="content">
        <div class="page-head">
          <div><h1>系统基础环境</h1><p>前端、API 与数据库连接状态，后续功能将在这套工程上逐项实现。</p></div>
          <button class="primary-btn" :disabled="loading" @click="refreshHealth"><RefreshCw :class="{ spin: loading }" />重新检测</button>
        </div>

        <section class="status-grid">
          <article class="status-card">
            <div class="status-top"><div class="status-icon"><Code2 /></div><span class="status-badge">运行正常</span></div>
            <h3>Vue 3 前端</h3><p>Vite + TypeScript + Element Plus</p>
          </article>
          <article class="status-card">
            <div class="status-top"><div class="status-icon"><Server /></div><span class="status-badge">{{ apiReady ? '连接成功' : '等待连接' }}</span></div>
            <h3>FastAPI 服务</h3><p>RESTful API 与 OpenAPI 文档已启用</p>
          </article>
          <article class="status-card">
            <div class="status-top"><div class="status-icon"><Database /></div><span class="status-badge">{{ dbReady ? '连接成功' : '等待连接' }}</span></div>
            <h3>MySQL 8 数据库</h3><p>独立库 geo_monitor_system</p>
          </article>
        </section>

        <section class="main-grid">
          <article class="panel">
            <div class="panel-head"><h2>工程落地路径</h2><span>当前：基础工程完成</span></div>
            <div class="flow">
              <div class="flow-item"><span class="flow-no">01</span><h3>工程骨架</h3><p>前后端分离、环境配置与统一接口</p></div>
              <div class="flow-item"><span class="flow-no">02</span><h3>数据底座</h3><p>租户、用户、菜单、权限与审计</p></div>
              <div class="flow-item"><span class="flow-no">03</span><h3>监测业务</h3><p>任务提交、结果同步、快照与统计</p></div>
              <div class="flow-item"><span class="flow-no">04</span><h3>运营交付</h3><p>诊断、报告、额度和平台管理</p></div>
            </div>
            <div class="api-detail" v-if="health">API: {{ health.service }} · DB: {{ health.database }} · {{ new Date(health.timestamp).toLocaleString() }}</div>
            <div class="api-detail" v-else>{{ error || '正在读取后端状态...' }}</div>
          </article>

          <article class="panel">
            <div class="panel-head"><h2>下一批功能</h2><span>按业务优先级推进</span></div>
            <div class="next-list">
              <div v-for="([icon, title, desc]) in nextModules" :key="title as string" class="next-item">
                <div class="next-icon"><component :is="icon" /></div>
                <div class="next-copy"><b>{{ title }}</b><span>{{ desc }}</span></div><ArrowRight class="arrow" />
              </div>
            </div>
          </article>
        </section>
      </main>
    </section>
  </div>
</template>

<style scoped>
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
