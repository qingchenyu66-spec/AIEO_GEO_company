<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listKeywordMinerExamples,
  updateKeywordMinerExample,
  type KeywordMinerExample,
} from '../../../services/keywordMiner'

const loading = ref(false)
const items = ref<KeywordMinerExample[]>([])
const q = ref('')
const industry = ref('')
const kind = ref('')
const status = ref('active')

async function load() {
  loading.value = true
  try {
    const data = await listKeywordMinerExamples({
      q: q.value.trim() || undefined,
      industry: industry.value.trim() || undefined,
      kind: kind.value || undefined,
      status: status.value || undefined,
      limit: 200,
    })
    items.value = data.items || []
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载范例库失败')
  } finally {
    loading.value = false
  }
}

async function toggleStatus(row: KeywordMinerExample) {
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

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="km-examples">
    <div class="km-examples-toolbar">
      <input v-model="industry" class="km-input" placeholder="行业" @keyup.enter="load" />
      <select v-model="kind" class="km-input" @change="load">
        <option value="">全部类型</option>
        <option value="select">选词</option>
        <option value="expand">拓词</option>
      </select>
      <select v-model="status" class="km-input" @change="load">
        <option value="active">启用中</option>
        <option value="disabled">已停用</option>
        <option value="">全部状态</option>
      </select>
      <input v-model="q" class="km-input km-input-wide" placeholder="搜索词/答案/改因" @keyup.enter="load" />
      <button type="button" class="primary-btn" :disabled="loading" @click="load">刷新</button>
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
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in items" :key="row.id">
          <td>{{ row.kind === 'expand' ? '拓词' : '选词' }}</td>
          <td>{{ row.industry || '—' }}</td>
          <td>{{ row.stage || '—' }}</td>
          <td>
            <div class="km-word">{{ row.word }}</div>
            <div v-if="row.answer" class="km-muted">{{ row.answer }}</div>
          </td>
          <td class="km-muted">{{ row.edit_reason || '—' }}</td>
          <td>{{ row.use_count }}</td>
          <td>{{ row.status === 'active' ? '启用' : '停用' }}</td>
          <td>
            <button type="button" class="plain-btn" @click="toggleStatus(row)">
              {{ row.status === 'active' ? '停用' : '启用' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
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
  border: 1px solid #d8dee9;
  border-radius: 8px;
  padding: 0 10px;
  min-width: 120px;
  background: #fff;
}

.km-input-wide {
  min-width: 220px;
  flex: 1;
}

.km-examples-empty {
  color: #6b7280;
  font-size: 13.5px;
  padding: 28px 8px;
}

.km-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.km-table th,
.km-table td {
  border-bottom: 1px solid #eef1f6;
  padding: 10px 8px;
  text-align: left;
  vertical-align: top;
}

.km-table th {
  color: #6b7280;
  font-weight: 600;
  background: #f8fafc;
}

.km-word {
  font-weight: 600;
  color: #1f2430;
}

.km-muted {
  color: #6b7280;
  font-size: 12px;
  margin-top: 4px;
  max-width: 420px;
}
</style>
