/** 与后端 tenant_logo_service 保持一致 */
export const TENANT_LOGO_ACCEPT = 'image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp'

export const TENANT_LOGO_MAX_BYTES = 2 * 1024 * 1024

export const TENANT_LOGO_MAX_MB = 2

/** 侧栏方标容器约 40×40，建议上传更高分辨率正方形 */
export const TENANT_LOGO_RECOMMENDED_PX = 128

export const TENANT_LOGO_HINT =
  `支持 PNG / JPG / WebP，单文件不超过 ${TENANT_LOGO_MAX_MB}MB。`
  + `建议正方形 ${TENANT_LOGO_RECOMMENDED_PX}×${TENANT_LOGO_RECOMMENDED_PX} 像素及以上（侧栏约 40×40 显示）；`
  + '浅色或白字 Logo 在浅色侧栏上可能看不清，请用彩色版或深色系素材。'
