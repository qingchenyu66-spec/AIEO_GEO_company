import { isRequestCanceled } from './requestError.ts'

const cases: Array<{ name: string; error: unknown; expect: boolean }> = [
  { name: 'axios canceled message', error: { message: 'canceled', code: 'ERR_CANCELED' }, expect: true },
  { name: 'CanceledError name', error: { name: 'CanceledError', message: 'canceled' }, expect: true },
  { name: 'AbortError', error: { name: 'AbortError' }, expect: true },
  { name: 'network', error: { message: 'Network Error' }, expect: false },
  { name: 'timeout', error: { message: 'timeout of 30000ms exceeded' }, expect: false },
]

for (const c of cases) {
  const got = isRequestCanceled(c.error)
  if (got !== c.expect) throw new Error(`${c.name}: got ${got}, expect ${c.expect}`)
}
console.log('ok requestError isRequestCanceled')
