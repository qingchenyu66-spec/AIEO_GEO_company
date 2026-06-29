export const platformLabelMap: Record<string, string> = {
  doubao: '豆包',
  doubao_mobile: '豆包（移动端）',
  deepseek: 'DeepSeek',
  deepseek_mobile: 'DeepSeek（移动端）',
  yuanbao: '元宝',
  kimi: 'Kimi',
  qianwen: '通义千问',
  quark: '夸克',
  baiduai: '百度 AI+',
  weibo_zhisou: '微博智搜',
  wenxinyiyan: '文心一言',
}

export const monitorModeLabelMap: Record<string, string> = {
  search: '搜索检测',
  chat: '问答检测',
  web: '网页检测',
}

export const monitorStatusLabelMap: Record<string, string> = {
  pending: '排队中',
  processing: '检测中',
  completed: '已完成',
  partial_completed: '部分完成',
  failed: '失败',
  stopped: '已停止',
}

export const sentimentLabelMap: Record<string, string> = {
  positive: '正面',
  neutral: '中性',
  negative: '负面',
}

export const supportedPlatforms = [
  { code: 'deepseek', name: 'DeepSeek' },
  { code: 'doubao', name: '豆包' },
  { code: 'yuanbao', name: '元宝' },
  { code: 'kimi', name: 'Kimi' },
  { code: 'qianwen', name: '通义千问' },
  { code: 'quark', name: '夸克' },
  { code: 'baiduai', name: '百度 AI+' },
  { code: 'weibo_zhisou', name: '微博智搜' },
  { code: 'wenxinyiyan', name: '文心一言' },
  { code: 'doubao_mobile', name: '豆包（移动端）' },
  { code: 'deepseek_mobile', name: 'DeepSeek（移动端）' },
]
