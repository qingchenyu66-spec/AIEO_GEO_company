export type SourceCategory = 'official' | 'media' | 'qa' | 'social' | 'encyclopedia'

export const sourceCategoryLabels: Record<SourceCategory, string> = {
  official: '官网/企业库',
  media: '行业媒体',
  qa: '问答社区',
  social: '社交媒体',
  encyclopedia: '百科',
}

export function sourceCategory(source: { title?: string; url?: string }): SourceCategory {
  const text = `${source.title || ''} ${source.url || ''}`.toLowerCase()
  if (text.includes('baike') || text.includes('百科')) return 'encyclopedia'
  if (text.includes('zhihu') || text.includes('知乎') || text.includes('问答')) return 'qa'
  if (text.includes('weibo') || text.includes('微博') || text.includes('douyin') || text.includes('小红书')) return 'social'
  if (text.includes('sohu') || text.includes('163.com') || text.includes('媒体') || text.includes('新闻') || text.includes('资讯')) return 'media'
  return 'official'
}
