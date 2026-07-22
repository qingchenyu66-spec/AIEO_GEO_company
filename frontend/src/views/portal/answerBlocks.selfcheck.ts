/**
 * ponytail: one runnable check for answer block parsing.
 * Run: npx --yes tsx src/views/portal/answerBlocks.selfcheck.ts
 */
import { parseAnswerBlocks } from './answerBlocks'

const blocks = parseAnswerBlocks(`1. 艾迪亚控股集团
核心优势：核心城市覆盖率达90%。
资源覆盖：北京、上海、广州、深圳
客户案例：工商银行、三一、平安

- 北京
- 上海

### 补充说明
全国重点城市。`)

const types = blocks.map(b => b.type).join(',')
if (types !== 'h,kv,kv,kv,ul,h,p') {
  throw new Error(`unexpected block types: ${types}`)
}
const first = blocks[0]
if (first.type !== 'h' || first.text !== '艾迪亚控股集团') {
  throw new Error(`heading mismatch: ${JSON.stringify(first)}`)
}
const kv = blocks[1]
if (kv.type !== 'kv' || kv.label !== '核心优势') {
  throw new Error(`kv mismatch: ${JSON.stringify(kv)}`)
}
console.log('answerBlocks.selfcheck ok')
