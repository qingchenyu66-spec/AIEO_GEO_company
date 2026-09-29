<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../../stores/auth'
import {
  listKeywordMinerExamples,
  updateKeywordMinerExample,
  type KeywordMinerExample,
} from '../../../services/keywordMiner'
import { KEYWORD_MINER_EXAMPLES_MENU, KEYWORD_MINER_MENU } from '../constants'

const PAGE_SIZE = 20

const auth = useAuthStore()
const loading = ref(false)
const items = ref<KeywordMinerExample[]>([])
const total = ref(0)
const page = ref(1)
const q = ref('')
const industry = ref('')
const kind = ref('')
const status = ref('active')

function menuOf(code: string) {
  return auth.allowedMenus.find(item => item.menu_code === code)
}

/** 停用/启用: 优先 can_delete, 兼容旧授权 can_update */
const canToggleStatus = computed(() => {
  const ex = menuOf(KEYWORD_MINER_EXAMPLES_MENU)
  const parent = menuOf(KEYWORD_MINER_MENU)
  return Boolean(
    ex?.can_delete || parent?.can_delete || ex?.can_update || parent?.can_update,
  )
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const rangeText = computed(() => {
  if (!total.value) return '共 0 条'
  const start = (page.value - 1) * PAGE_SIZE + 1
  const end = Math.min(page.value * PAGE_SIZE, total.value)
  return `第 ${start}-${end} 条 / 共 ${total.value} 条`
})

async function load() {
  loading.value = true
  try {
    const data = await listKeywordMinerExamples({
      q: q.value.trim() || undefined,
      industry: industry.value.trim() || undefined,
      kind: kind.value || undefined,
      status: status.value || undefined,
      limit: PAGE_SIZE,
      offset: (page.value - 1) * PAGE_SIZE,
    })
    items.value = data.items || []
    total.value = Number(data.total || 0)
    if (page.value > totalPages.value) {
      page.value = totalPages.value
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载范例库失败')
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}

function goPrev() {
  if (page.value <= 1) return
  page.value -= 1
  void load()
}

function goNext() {
  if (page.value >= totalPages.value) return
  page.value += 1
  void load()
}

async function toggleStatus(row: KeywordMinerExample) {
  if (!canToggleStatus.value) {
    ElMessage.warning('当前账号无权停用/启用范例')
    return
  }
  const next = row.status === 'active' ? 'disabled' : 'active'
  const label = next === 'active' ? '启用' : '停用'
  try {
    await ElMessageBox.confirm(`确定${label}该范例？`, '确认', { type: 'warning' })
    await updateKeywordMinerExample(row.id, { status: next })
    ElMessage.success(`已${label}`)
    await load()
  } catch {
    /* cancel */
  }
}

watch([kind, status], () => {
  page.value = 1
  void load()
})

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="km-examples">
    <div class="km-examples-toolbar">
      <input v-model="industry" class="km-input" placeholder="行业" @keyup.enter="search" />
      <select v-model="kind" class="km-input">
        <option value="">全部类型</option>
        <option value="select">选词</option>
        <option value="expand">拓词</option>
      </select>
      <select v-model="status" class="km-input">
        <option value="active">启用中</option>
        <option value="disabled">已停用</option>
        <option value="">全部状态</option>
      </select>
      <input v-model="q" class="km-input km-input-wide" placeholder="搜索词/答案/改因" @keyup.enter="search" />
      <button type="button" class="primary-btn" :disabled="loading" @click="search">刷新</button>
    </div>

    <div v-if="loading" class="km-examples-empty">加载中…</div>
    <div v-else-if="!items.length" class="km-examples-empty">暂无范例。可在选词台勾选结果后「加入范例库」。</div>
    <table v-else class="km-table">
      <thead>
        <tr>
          <th>类型</th>
          <th>行业</th>
          <th>阶段/类目</th>
          <th>词</th>
          <th>改因</th>
          <th>引用</th>
          <th>状态</th>
          <th v-if="canToggleStatus">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in items" :key="row.id">
          <td>{{ row.kind === 'select' ? '选词' : '拓词' }}</td>
          <td>{{ row.industry || '—' }}</td>
          <td>{{ row.stage || '—' }}</td>
          <td>
            <div class="km-word">{{ row.word }}</div>
            <div v-if="row.answer" class="km-muted">{{ row.answer }}</div>
          </td>
          <td class="km-muted">{{ row.edit_reason || '—' }}</td>
          <td>{{ row.use_count }}</td>
          <td>{{ row.status === 'active' ? '启用' : '停用' }}</td>
          <td v-if="canToggleStatus">
            <button type="button" class="plain-btn" @click="toggleStatus(row)">
              {{ row.status === 'active' ? '停用' : '启用' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="total > 0" class="km-pager">
      <span class="km-pager-meta">{{ rangeText }}</span>
      <div class="km-pager-actions">
        <button type="button" class="plain-btn" :disabled="loading || page <= 1" @click="goPrev">上一页</button>
        <span class="km-pager-page">{{ page }} / {{ totalPages }}</span>
        <button type="button" class="plain-btn" :disabled="loading || page >= totalPages" @click="goNext">下一页</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.km-examples {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 12px 16px 20px;
  gap: 12px;
  overflow: auto;
  background: #fff;
}

.km-examples-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.km-input {
  height: 34px;
  border: 1px solid #d0d7e2;
  border-radius: 8px;
  padding: 0 10px;
  font: inherit;
  background: #fff;
}

.km-input-wide { min-width: 220px; flex: 1; }

.km-examples-empty {
  color: #6b7280;
  font-size: 13px;
  padding: 24px 4px;
}

.km-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.km-table th,
.km-table td {
  text-align: left;
  padding: 10px 8px;
  border-bottom: 1px solid #e5e8ef;
  vertical-align: top;
}

.km-table th {
  color: #6b7280;
  font-weight: 600;
  background: #f7f8fb;
}

.km-word { font-weight: 600; }
.km-muted { color: #6b7280; font-size: 12px; margin-top: 4px; line-height: 1.4; }

.primary-btn,
.plain-btn {
  height: 34px;
  border-radius: 8px;
  padding: 0 12px;
  font: inherit;
  cursor: pointer;
}

.primary-btn {
  border: 0;
  background: #185fa5;
  color: #fff;
}

.plain-btn {
  border: 1px solid #d0d7e2;
  background: #fff;
  color: #185fa5;
}

.primary-btn:disabled,
.plain-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.km-pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 4px;
}

.km-pager-meta {
  color: #6b7280;
  font-size: 12.5px;
}

.km-pager-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.km-pager-page {
  min-width: 64px;
  text-align: center;
  color: #374151;
  font-size: 13px;
}
</style>
