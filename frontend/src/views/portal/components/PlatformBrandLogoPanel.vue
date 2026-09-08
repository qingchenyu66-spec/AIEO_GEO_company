<script setup lang="ts">
import { onMounted, ref, inject } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import TenantLogoField from '../../../components/TenantLogoField.vue'
import { TENANT_LOGO_MAX_BYTES } from '../../../constants/tenantLogo'
import {
  clearPlatformLogo,
  getPlatformLogoMeta,
  platformLogoUrl,
  uploadPlatformLogo,
  type PlatformLogoMeta,
} from '../../../services/management'
import { extractErrorDetail } from '../../../utils/requestError'
import { PlatformDefaultLogoRefreshKey } from '../injectionKeys'

const props = defineProps<{ canEdit?: boolean }>()
const refreshPortalLogo = inject(PlatformDefaultLogoRefreshKey, null)

const loading = ref(false)
const saving = ref(false)
const meta = ref<PlatformLogoMeta>({ has_logo: false, logo_updated_at: null })
const pendingFile = ref<File | null>(null)
const pendingPreview = ref<string | null>(null)
const pendingName = ref('')

function revokePending() {
  if (pendingPreview.value?.startsWith('blob:')) URL.revokeObjectURL(pendingPreview.value)
  pendingPreview.value = null
  pendingFile.value = null
  pendingName.value = ''
}

async function loadMeta() {
  loading.value = true
  try {
    meta.value = await getPlatformLogoMeta()
  } catch (error) {
    ElMessage.error(extractErrorDetail(error) || '加载平台 Logo 失败')
  } finally {
    loading.value = false
  }
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > TENANT_LOGO_MAX_BYTES) {
    ElMessage.warning('Logo 不能超过 2MB')
    return
  }
  revokePending()
  pendingFile.value = file
  pendingName.value = file.name
  pendingPreview.value = URL.createObjectURL(file)
}

function onClearPending() {
  revokePending()
}

async function afterChanged(next: PlatformLogoMeta) {
  meta.value = next
  if (refreshPortalLogo) await refreshPortalLogo()
}

async function saveUpload() {
  if (!pendingFile.value || !props.canEdit) return
  saving.value = true
  try {
    const next = await uploadPlatformLogo(pendingFile.value)
    revokePending()
    await afterChanged(next)
    ElMessage.success('平台默认 Logo 已更新')
  } catch (error) {
    ElMessage.error(extractErrorDetail(error) || '上传失败')
  } finally {
    saving.value = false
  }
}

async function restoreDefault() {
  if (!props.canEdit) return
  try {
    await ElMessageBox.confirm('恢复为内置亦智方标？当前自定义平台 Logo 将被删除。', '恢复默认', {
      type: 'warning',
      confirmButtonText: '恢复',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  saving.value = true
  try {
    const next = await clearPlatformLogo()
    revokePending()
    await afterChanged(next)
    ElMessage.success('已恢复内置默认标')
  } catch (error) {
    ElMessage.error(extractErrorDetail(error) || '恢复失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void loadMeta()
})
</script>

<template>
  <div v-loading="loading" class="platform-brand-logo-panel">
    <TenantLogoField
      :preview-src="pendingPreview || (meta.has_logo ? platformLogoUrl(meta.logo_updated_at) : undefined)"
      :file-name="pendingName || undefined"
      :disabled="!canEdit || saving"
      @pick="onPick"
      @clear="onClearPending"
    />
    <div class="platform-brand-logo-panel__actions">
      <button
        type="button"
        class="primary-btn small-btn"
        :disabled="!canEdit || !pendingFile || saving"
        @click="saveUpload"
      >
        保存上传
      </button>
      <button
        type="button"
        class="plain-btn small-btn"
        :disabled="!canEdit || !meta.has_logo || saving"
        @click="restoreDefault"
      >
        恢复内置默认
      </button>
    </div>
  </div>
</template>

<style scoped>
.platform-brand-logo-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
</style>
