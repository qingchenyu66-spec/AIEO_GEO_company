/** 任务配置展示：问法打标（对齐驾驶舱可见意图，仅前端展示用）。 */

const INTENT_RULES: Array<{ code: string; label: string; keys: string[] }> = [
  {
    code: 'recommend',
    label: '推荐名单',
    keys: [
      '推荐', '哪家好', '哪家强', '哪家比较', '哪家靠谱', '哪家更', '服务商哪家',
      '排行', '排名', 'top', 'TOP', '名单', '值得推荐', '怎么选', '如何选', '选购', '供应商怎么选',
      '选择标准', '选型',
    ],
  },
  { code: 'compare', label: '竞品对标', keys: ['对比', 'vs', 'VS', '还是', '和谁', '竞品', '哪家更好'] },
  { code: 'reputation', label: '口碑评价', keys: ['靠谱吗', '怎么样', '好不好', '评价', '口碑', '坑', '靠不靠谱', '客户评价'] },
  { code: 'awareness', label: '品牌认知', keys: ['是什么', '介绍', '了解', '品牌', '公司简介'] },
]

export function displayOrEmpty(value: unknown): string {
  const text = String(value ?? '').trim()
  return text || '未填写'
}

export function promptContainsBrand(prompt: string, brand: string, aliases: string[] = []): boolean {
  const text = String(prompt || '')
  const terms = [brand, ...aliases].map((x) => String(x || '').trim()).filter(Boolean)
  return terms.some((term) => term.length >= 2 && text.includes(term))
}

export function classifyLeadConfigPrompt(
  prompt: string,
  brand: string,
  aliases: string[] = [],
): { laneLabel: string; reportLabel: string; isBrand: boolean } {
  const text = String(prompt || '').trim()
  const isBrand = promptContainsBrand(text, brand, aliases)
  let reportLabel = '品牌认知'
  for (const rule of INTENT_RULES) {
    if (rule.keys.some((k) => text.includes(k))) {
      reportLabel = rule.label
      break
    }
  }
  return {
    isBrand,
    laneLabel: isBrand ? '品牌防守' : '非品牌获客',
    reportLabel,
  }
}
