/**
 * Customer portal preview helpers — keep menu codes and query fields stable.
 * Run: npx --yes tsx frontend/src/views/portal/customerPreview.selfcheck.ts
 */
import {
  CUSTOMER_PREVIEW_MENU_CODES,
  isCustomerPreviewMenuCode,
  previewQueryFields,
  resolvePreviewTenantId,
} from './customerPreview'

const expected = [
  'customer.workspace',
  'customer.brand_analysis',
  'customer.realtime',
  'customer.competitor',
  'customer.sources',
  'customer.reports',
  'customer.knowledge',
]

if (CUSTOMER_PREVIEW_MENU_CODES.length !== 7) {
  throw new Error(`expected 7 preview menus, got ${CUSTOMER_PREVIEW_MENU_CODES.length}`)
}
for (const code of expected) {
  if (!isCustomerPreviewMenuCode(code)) throw new Error(`missing preview menu ${code}`)
}
if (isCustomerPreviewMenuCode('platform.audit')) {
  throw new Error('platform.audit must not be a preview menu')
}
const q = previewQueryFields(6, '艾迪亚')
if (q.preview_tenant_id !== '6' || q.tenant_id !== '6' || q.preview_tenant_name !== '艾迪亚') {
  throw new Error(`bad preview query: ${JSON.stringify(q)}`)
}
const entering = resolvePreviewTenantId(
  { query: {} } as never,
  { preview_tenant_id: '14', preview_tenant_name: '交通业' },
)
if (entering !== 14) throw new Error(`resolvePreviewTenantId from extra failed: ${entering}`)
const sticky = resolvePreviewTenantId(
  { query: { preview_tenant_id: '6' } } as never,
  undefined,
)
if (sticky !== 6) throw new Error(`resolvePreviewTenantId from route failed: ${sticky}`)
console.log('customerPreview.selfcheck ok')
