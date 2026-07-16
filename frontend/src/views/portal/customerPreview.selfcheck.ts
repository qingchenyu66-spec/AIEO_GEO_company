/**
 * Customer portal preview helpers — keep menu codes and query fields stable.
 * Run: npx --yes tsx frontend/src/views/portal/customerPreview.selfcheck.ts
 */
import {
  CUSTOMER_PREVIEW_MENU_CODES,
  isCustomerPreviewMenuCode,
  previewQueryFields,
} from './customerPreview'

const expected = [
  'customer.workspace',
  'customer.realtime',
  'customer.competitor',
  'customer.sources',
  'customer.reports',
  'customer.knowledge',
]

if (CUSTOMER_PREVIEW_MENU_CODES.length !== 6) {
  throw new Error(`expected 6 preview menus, got ${CUSTOMER_PREVIEW_MENU_CODES.length}`)
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
console.log('customerPreview.selfcheck ok')
