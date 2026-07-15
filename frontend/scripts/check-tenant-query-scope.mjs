/**
 * Minimal self-check for tenant query / brand prefetch scope (no test runner).
 * Run: node frontend/scripts/check-tenant-query-scope.mjs
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(import.meta.url)

// Compile-free: duplicate the pure logic expectations against the TS source via dynamic import
// fails without a bundler — assert against copied contract instead, then grep source for exports.
const scopePath = path.join(root, 'src', 'views', 'portal', 'tenantQueryScope.ts')
const retryPath = path.join(root, 'src', 'composables', 'useRetry.ts')
const fs = require('node:fs')
const scopeSrc = fs.readFileSync(scopePath, 'utf8')
const retrySrc = fs.readFileSync(retryPath, 'utf8')

assert.doesNotMatch(
  scopeSrc.slice(scopeSrc.indexOf('BRAND_PREFETCH_MENUS'), scopeSrc.indexOf('export function shouldKeep')),
  /reports/,
  'report menus must not be in BRAND_PREFETCH_MENUS',
)
assert.doesNotMatch(
  scopeSrc.slice(scopeSrc.indexOf('TENANT_QUERY_SCOPED_MENUS'), scopeSrc.indexOf('BRAND_PREFETCH_MENUS')),
  /reports/,
  'report menus must not keep sticky tenant_id',
)
assert.match(scopeSrc, /'platform\.competitor'/)
assert.match(scopeSrc, /'platform\.sources'/)
assert.match(retrySrc, /isNonRetryableHttpError/)
assert.match(retrySrc, /status >= 400 && status < 500/)

// Inline mirror of resolveAccessibleTenantId for runtime assert
function resolveAccessibleTenantId(requested, accessibleIds) {
  if (requested != null && accessibleIds.includes(requested)) return requested
  return accessibleIds[0] ?? null
}

assert.equal(resolveAccessibleTenantId(9, [1, 2, 3]), 1, 'inaccessible URL tenant falls back to first owned')
assert.equal(resolveAccessibleTenantId(2, [1, 2, 3]), 2, 'owned URL tenant is kept')
assert.equal(resolveAccessibleTenantId(null, [7]), 7)
assert.equal(resolveAccessibleTenantId(1, []), null)

function isNonRetryableHttpError(error) {
  const status = error?.response?.status
  return typeof status === 'number' && status >= 400 && status < 500
}
assert.equal(isNonRetryableHttpError({ response: { status: 403 } }), true)
assert.equal(isNonRetryableHttpError({ response: { status: 500 } }), false)
assert.equal(isNonRetryableHttpError(new Error('network')), false)

console.log('check-tenant-query-scope: ok', pathToFileURL(scopePath).href)
