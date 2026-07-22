/** Lightweight answer text → blocks for snapshot dialogs (no markdown lib). */

export type AnswerBlock =
  | { type: 'h'; text: string }
  | { type: 'p'; text: string }
  | { type: 'ul'; items: string[] }
  | { type: 'ol'; items: string[] }
  | { type: 'kv'; label: string; value: string }

function stripInlineBold(text: string) {
  return text.replace(/\*\*(.+?)\*\*/g, '$1').trim()
}

/** Short numbered line → section title (e.g. "1. 艾迪亚控股集团") */
function numberedHeading(line: string): string | null {
  const m = line.match(/^\s*(\d+)[.)、]\s+(.+)$/)
  if (!m) return null
  const body = m[2].trim()
  // Long bodies are real ordered-list items; short ones are company/section titles
  if (body.length > 48 || /[。；;]$/.test(body)) return null
  return stripInlineBold(body)
}

function fieldLine(line: string): { label: string; value: string } | null {
  const m = line.match(/^[\s　]*([^：:\n]{2,16})[：:]\s*(.+)$/)
  if (!m) return null
  const label = stripInlineBold(m[1])
  const value = stripInlineBold(m[2])
  if (!label || !value) return null
  // Avoid treating URLs / times as fields
  if (/^https?:\/\//i.test(label)) return null
  return { label, value }
}

export function parseAnswerBlocks(raw: string): AnswerBlock[] {
  const lines = raw.replace(/\r\n/g, '\n').split('\n')
  const blocks: AnswerBlock[] = []
  let para: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null

  const flushPara = () => {
    const text = stripInlineBold(para.join('\n').trim())
    if (text) blocks.push({ type: 'p', text })
    para = []
  }
  const flushList = () => {
    if (list?.items.length) {
      blocks.push({
        type: list.ordered ? 'ol' : 'ul',
        items: list.items.map(stripInlineBold),
      })
    }
    list = null
  }

  for (const line of lines) {
    const headingMd = line.match(/^#{1,3}\s+(.+)$/) || line.match(/^\*\*(.+?)\*\*\s*$/)
    const numHead = numberedHeading(line)
    const field = fieldLine(line)
    const ul = line.match(/^\s*[-*•●·]\s+(.+)$/)
    const ol = line.match(/^\s*\d+[.)、]\s+(.+)$/)

    if (headingMd) {
      flushPara()
      flushList()
      blocks.push({ type: 'h', text: stripInlineBold(headingMd[1]) })
      continue
    }
    if (numHead) {
      flushPara()
      flushList()
      blocks.push({ type: 'h', text: numHead })
      continue
    }
    if (field) {
      flushPara()
      flushList()
      blocks.push({ type: 'kv', label: field.label, value: field.value })
      continue
    }
    if (ul) {
      flushPara()
      if (!list || list.ordered) {
        flushList()
        list = { ordered: false, items: [] }
      }
      list.items.push(ul[1])
      continue
    }
    if (ol) {
      flushPara()
      if (!list || !list.ordered) {
        flushList()
        list = { ordered: true, items: [] }
      }
      list.items.push(ol[1])
      continue
    }
    if (!line.trim()) {
      flushPara()
      flushList()
      continue
    }
    flushList()
    para.push(line)
  }
  flushPara()
  flushList()
  return blocks
}
