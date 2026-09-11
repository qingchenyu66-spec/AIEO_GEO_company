<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  listCreditPriceRules,
  listCreditTerms,
  publishCreditTerms,
  upsertCreditPriceRule,
  type CreditPriceRuleItem,
} from '../../../services/credit'
import { extractErrorDetail } from '../../../utils/requestError'
import { platformLabelMap, supportedPlatforms } from '../portalMaps'
import AnnouncementEditor from './AnnouncementEditor.vue'

const props = defineProps<{ canEdit: boolean }>()

const DEEP_THINK_ADDON_CODE = 'deep_think_addon'
const TERMS_PAGE_SIZE = 10

const GLOBAL_PLATFORM_CODES: Array<string | null> = [
  null,
  ...supportedPlatforms.map(item => item.code),
  DEEP_THINK_ADDON_CODE,
]

type EditablePriceRow = {
  key: string
  id: number | null
  platform_code: string | null
  platform_label: string
  credits_per_subtask: number
  status: boolean
  inherited: boolean
  saving: boolean
  baseline_credits: number
  baseline_status: boolean
}

const loading = ref(false)
const terms = ref<Array<Record<string, unknown>>>([])
const termsPage = ref(1)
const priceRows = ref<EditablePriceRow[]>([])
const termsForm = ref({
  version_code: '',
  title: '',
  content_html: '',
  effective_at: '',
  notice_days: 7,
})
const publishing = ref(false)
const termsPreviewVisible = ref(false)
const termsPreviewRow = ref<Record<string, unknown> | null>(null)

const termsPageCount = computed(() => Math.max(1, Math.ceil(terms.value.length / TERMS_PAGE_SIZE)))
const termsPagerVisible = computed(() => terms.value.length > TERMS_PAGE_SIZE)
const visibleTerms = computed(() => {
  const start = (termsPage.value - 1) * TERMS_PAGE_SIZE
  return terms.value.slice(start, start + TERMS_PAGE_SIZE)
})

const termsPreviewTitle = computed(() => {
  // 2026-09-08 - 弹窗标题与正文 h3 重复难看 - 预览统一用短标题
  return '服务条款预览'
})

watch(termsPageCount, (count) => {
  if (termsPage.value > count) termsPage.value = count
})

function openTermsPreview(row: Record<string, unknown>) {
  termsPreviewRow.value = row
  termsPreviewVisible.value = true
}

function platformPriceLabel(code: string | null) {
  if (code === null) return '默认（未单独定价）'
  if (code === DEEP_THINK_ADDON_CODE) return '深度思考增加额度'
  return platformLabelMap[code] || code
}

function rowKey(code: string | null) {
  return code ?? '__default__'
}

function termsStatusLabel(status: unknown) {
  const key = String(status || '')
  if (key === 'published') return '已发布'
  if (key === 'draft') return '草稿'
  if (key === 'scheduled') return '待生效'
  return key || '—'
}

function formatEffectiveAt(value: unknown) {
  const raw = String(value || '').trim()
  if (!raw) return '—'
  // 2026-09-08 - 生效日 ISO 太长挤版 - 展示到分钟
  return raw.replace('T', ' ').slice(0, 16)
}

function buildGlobalPriceRows(rules: CreditPriceRuleItem[]): EditablePriceRow[] {
  const globalRules = rules.filter(row => row.scope === 'global')
  const defaultRule = globalRules.find(row => !row.platform_code)
  const defaultCredits = Number(defaultRule?.credits_per_subtask ?? 1)
  const defaultStatus = defaultRule?.status ?? true

  return GLOBAL_PLATFORM_CODES.map((code) => {
    const existing = globalRules.find(row => (row.platform_code || null) === code)
    const credits = Number(existing?.credits_per_subtask ?? defaultCredits)
    const status = existing?.status ?? true
    // 2026-09-08 - 夸克/Kimi 有同价单独行却不显示沿用默认 - 与默认单价且启用态一致也算沿用
    const inherited = code !== null && (
      !existing
      || (
        code !== DEEP_THINK_ADDON_CODE
        && credits === defaultCredits
        && Boolean(status) === Boolean(defaultStatus)
      )
    )
    return {
      key: rowKey(code),
      id: existing?.id ?? null,
      platform_code: code,
      platform_label: platformPriceLabel(code),
      credits_per_subtask: credits,
      status,
      inherited,
      saving: false,
      baseline_credits: credits,
      baseline_status: status,
    }
  })
}

async function reloadPriceRules() {
  const rules = await listCreditPriceRules('global')
  priceRows.value = buildGlobalPriceRows(rules)
}

async function load() {
  loading.value = true
  try {
    terms.value = await listCreditTerms()
    await reloadPriceRules()
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '加载算力计费配置失败'))
  } finally {
    loading.value = false
  }
}

async function submitTerms() {
  if (!props.canEdit) return
  publishing.value = true
  try {
    await publishCreditTerms({
      ...termsForm.value,
      effective_at: termsForm.value.effective_at || new Date().toISOString().slice(0, 16),
    })
    ElMessage.success('规则已发布')
    termsForm.value = { version_code: '', title: '', content_html: '', effective_at: '', notice_days: 7 }
    terms.value = await listCreditTerms()
    termsPage.value = 1
  } catch (error) {
    ElMessage.error(extractErrorDetail(error, '发布失败'))
  } finally {
    publishing.value = false
  }
}

async function savePriceRow(row: EditablePriceRow) {
  if (!props.canEdit || row.saving) return
  const credits = Number(row.credits_per_subtask)
  if (!Number.isFinite(credits) || credits <= 0) {
    ElMessage.warning('单价须大于 0')
    row.credits_per_subtask = row.baseline_credits
    return
  }
  if (
    credits === row.baseline_credits
    && row.status === row.baseline_status
  ) {
    return
  }
  row.saving = true
  try {
    await upsertCreditPriceRule({
      scope: 'global',
      tenant_id: null,
      platform_code: row.platform_code,
      credits_per_subtask: credits,
      status: row.status,
    })
    row.inherited = false
    row.baseline_credits = credits
    row.baseline_status = row.status
    await reloadPriceRules()
  } catch (error) {
    row.credits_per_subtask = row.baseline_credits
    row.status = row.baseline_status
    ElMessage.error(extractErrorDetail(error, '保存失败'))
  } finally {
    row.saving = false
  }
}

function onCreditsBlur(row: EditablePriceRow) {
  void savePriceRow(row)
}

function onStatusChange(row: EditablePriceRow) {
  void savePriceRow(row)
}

onMounted(load)
</script>

<template>
  <!-- 2026-09-08 - 定价与条款版面乱 - 对齐算力运营分区表；去掉恒为「全局/—」的空列；发布与历史拆开 -->
  <div class="credit-billing-config" v-loading="loading">
    <article class="panel billing-section">
      <div class="panel-head">
        <h2>全局单价</h2>
      </div>
      <div class="billing-data-table">
        <div class="billing-data-head billing-price-cols">
          <span>平台</span>
          <span>算力 / 子任务</span>
          <span>状态</span>
        </div>
        <div
          v-for="row in priceRows"
          :key="row.key"
          class="billing-data-row billing-price-cols"
          :class="{ inherited: row.inherited, addon: row.platform_code === DEEP_THINK_ADDON_CODE }"
        >
          <span class="cell-platform">
            {{ row.platform_label }}
            <em v-if="row.inherited">沿用默认</em>
          </span>
          <span class="cell-credits">
            <input
              v-if="canEdit"
              v-model.number="row.credits_per_subtask"
              type="number"
              step="0.01"
              min="0.01"
              class="cell-input"
              :disabled="row.saving"
              @blur="onCreditsBlur(row)"
              @keydown.enter="($event.target as HTMLInputElement)?.blur()"
            >
            <template v-else>{{ row.credits_per_subtask }}</template>
          </span>
          <span>
            <select
              v-if="canEdit"
              v-model="row.status"
              class="cell-input cell-select"
              :disabled="row.saving"
              @change="onStatusChange(row)"
            >
              <option :value="true">启用</option>
              <option :value="false">停用</option>
            </select>
            <template v-else>{{ row.status ? '启用' : '停用' }}</template>
          </span>
        </div>
      </div>
    </article>

    <div class="billing-terms-layout" :class="{ 'is-single': !canEdit }">
      <article v-if="canEdit" class="panel billing-section">
        <div class="panel-head">
          <h2>发布新版本</h2>
        </div>
        <div class="billing-publish-grid">
          <label>
            <span>版本号</span>
            <input v-model="termsForm.version_code" placeholder="如 2026-09-08">
          </label>
          <label>
            <span>标题</span>
            <input v-model="termsForm.title" placeholder="服务条款标题">
          </label>
          <label>
            <span>生效时间</span>
            <input v-model="termsForm.effective_at" type="datetime-local">
          </label>
          <!-- 2026-09-08 - 条款正文复用公告富文本，避免手写 HTML -->
          <div class="span-2 billing-terms-editor">
            <span>正文</span>
            <AnnouncementEditor v-model="termsForm.content_html" />
          </div>
        </div>
        <div class="billing-publish-footer">
          <button type="button" class="primary-btn small-btn" :disabled="publishing" @click="submitTerms">
            {{ publishing ? '发布中…' : '发布新版本' }}
          </button>
        </div>
      </article>

      <article class="panel billing-section">
        <div class="panel-head">
          <h2>规则声明版本</h2>
          <span v-if="terms.length">共 {{ terms.length }} 条</span>
        </div>
        <div class="billing-data-table">
          <div class="billing-data-head billing-terms-cols">
            <span>版本</span>
            <span>生效日</span>
            <span>状态</span>
            <span>操作</span>
          </div>
          <div
            v-for="row in visibleTerms"
            :key="String(row.id)"
            class="billing-data-row billing-terms-cols"
          >
            <span class="cell-version" :title="String(row.version_code || '')">{{ row.version_code }}</span>
            <span>{{ formatEffectiveAt(row.effective_at) }}</span>
            <span>{{ termsStatusLabel(row.status) }}</span>
            <span>
              <button type="button" class="billing-link-btn" @click="openTermsPreview(row)">预览</button>
            </span>
          </div>
          <div v-if="!terms.length" class="billing-empty">暂无已发布规则</div>
        </div>
        <div v-if="termsPagerVisible" class="log-pagination">
          <span class="log-pagination-meta">第 {{ termsPage }} / {{ termsPageCount }} 页 · 每页 {{ TERMS_PAGE_SIZE }} 条</span>
          <div class="log-pagination-actions">
            <button type="button" class="filter-reset-btn tiny-btn" :disabled="termsPage <= 1" @click="termsPage -= 1">上一页</button>
            <button type="button" class="filter-reset-btn tiny-btn" :disabled="termsPage >= termsPageCount" @click="termsPage += 1">下一页</button>
          </div>
        </div>
      </article>
    </div>

    <el-dialog v-model="termsPreviewVisible" width="640px" :title="termsPreviewTitle" destroy-on-close>
      <div
        v-if="termsPreviewRow?.content_html"
        class="terms-preview-body"
        v-html="String(termsPreviewRow.content_html)"
      />
      <p v-else class="billing-empty">暂无正文</p>
    </el-dialog>
  </div>
</template>

<style scoped>
.credit-billing-config {
  display: grid;
  gap: 16px;
}
.billing-section {
  padding: 0;
  overflow: hidden;
}
.billing-section > .panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 18px 0;
  margin-bottom: 0;
}
.billing-section > .panel-head h2 {
  margin: 0;
  font-size: 18px;
  color: #17233d;
}
.billing-section > .panel-head span {
  color: #7890ab;
  font-size: 12px;
}
.billing-data-table {
  overflow: hidden;
  margin: 12px 18px 14px;
  border: 1px solid #d9e8f6;
  border-radius: 12px;
  background: #fff;
}
.billing-data-head,
.billing-data-row {
  display: grid;
  gap: 12px;
  align-items: center;
  padding: 12px 16px;
  font-size: 13px;
}
.billing-data-head {
  color: #607692;
  background: #f2f7fc;
  font-weight: 800;
}
.billing-data-row {
  border-top: 1px solid #edf3fa;
  color: #1a3656;
}
.billing-data-row.inherited {
  color: #64748b;
}
.billing-data-row.addon {
  background: #f8fafc;
}
.billing-price-cols {
  grid-template-columns: minmax(180px, 1.6fr) 140px 120px;
}
.billing-terms-cols {
  grid-template-columns: minmax(160px, 1.6fr) 140px 72px 64px;
}
.cell-platform {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: #10233f;
  word-break: break-word;
}
.billing-data-row.inherited .cell-platform {
  font-weight: 600;
  color: #64748b;
}
.cell-platform em {
  font-style: normal;
  font-weight: 600;
  font-size: 11px;
  color: #607692;
  background: #eef4fb;
  border-radius: 999px;
  padding: 2px 8px;
}
.cell-credits {
  display: flex;
  justify-content: flex-end;
}
.billing-price-cols > :nth-child(2),
.billing-price-cols > :nth-child(3) {
  text-align: right;
}
.cell-version {
  font-weight: 600;
  color: #10233f;
  word-break: break-all;
}
.billing-link-btn {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--el-color-primary);
  font-size: 13px;
  cursor: pointer;
}
.billing-link-btn:hover { text-decoration: underline; }
.terms-preview-body {
  max-height: 60vh;
  overflow: auto;
  font-size: 13px;
  line-height: 1.65;
  color: #1a3656;
}
.terms-preview-body :deep(h3),
.terms-preview-body :deep(h4) {
  margin: 0.8em 0 0.4em;
  color: #10233f;
}
.terms-preview-body :deep(p),
.terms-preview-body :deep(ol),
.terms-preview-body :deep(ul) {
  margin: 0.4em 0;
}
.terms-preview-body :deep(li) {
  margin: 0.2em 0;
}
.cell-input {
  width: 100%;
  max-width: 120px;
  min-height: 32px;
  border: 1px solid #d8e7f6;
  border-radius: 8px;
  padding: 4px 8px;
  font-size: 13px;
  background: #fff;
  color: #153052;
  text-align: right;
}
.cell-select {
  max-width: 96px;
  text-align: left;
}
.cell-input:disabled {
  opacity: 0.6;
}
.billing-empty {
  padding: 28px 16px;
  text-align: center;
  color: #7890ab;
  font-size: 13px;
}
.billing-section > .log-pagination {
  margin: 0;
  border-top: 1px solid #edf3fa;
  padding: 10px 18px 14px;
}
.billing-terms-layout {
  display: grid;
  gap: 16px;
  /* 2026-09-08 - 富文本编辑要宽，发布与版本改为上下排 */
  grid-template-columns: 1fr;
  align-items: start;
}
.billing-terms-layout.is-single {
  grid-template-columns: 1fr;
}
.billing-publish-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px 14px;
  padding: 14px 18px 0;
}
.billing-publish-grid label {
  display: grid;
  gap: 6px;
}
.billing-publish-grid label.span-2,
.billing-publish-grid .span-2 {
  grid-column: 1 / -1;
}
.billing-terms-editor {
  display: grid;
  gap: 6px;
}
.billing-terms-editor > span {
  color: #536a86;
  font-size: 12px;
  font-weight: 600;
}
.billing-publish-grid span {
  color: #536a86;
  font-size: 12px;
  font-weight: 600;
}
.billing-publish-grid input,
.billing-publish-grid textarea {
  width: 100%;
  border: 1px solid #d8e7f6;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  color: #153052;
  background: #fff;
}
.billing-publish-footer {
  display: flex;
  justify-content: flex-end;
  padding: 12px 18px 16px;
}
@media (max-width: 960px) {
  .billing-publish-grid {
    grid-template-columns: 1fr;
  }
}
</style>
