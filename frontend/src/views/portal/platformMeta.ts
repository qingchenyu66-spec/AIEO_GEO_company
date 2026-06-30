export interface PlatformMeta {
  code: string
  name: string
  accent: string
  icon: string
}

const PLATFORM_META: Record<string, PlatformMeta> = {
  deepseek: {
    code: 'deepseek',
    name: 'DeepSeek',
    accent: '#4d6bfe',
    icon: '/platform-icons/deepseek.svg',
  },
  deepseek_mobile: {
    code: 'deepseek_mobile',
    name: 'DeepSeek（移动端）',
    accent: '#4d6bfe',
    icon: '/platform-icons/deepseek.svg',
  },
  doubao: {
    code: 'doubao',
    name: '豆包',
    accent: '#ff7a45',
    icon: '/platform-icons/doubao.svg',
  },
  doubao_mobile: {
    code: 'doubao_mobile',
    name: '豆包（移动端）',
    accent: '#ff7a45',
    icon: '/platform-icons/doubao.svg',
  },
  yuanbao: {
    code: 'yuanbao',
    name: '元宝',
    accent: '#07c160',
    icon: '/platform-icons/yuanbao.svg',
  },
  kimi: {
    code: 'kimi',
    name: 'Kimi',
    accent: '#111827',
    icon: '/platform-icons/kimi.svg',
  },
  qianwen: {
    code: 'qianwen',
    name: '通义千问',
    accent: '#615ced',
    icon: '/platform-icons/qianwen.svg',
  },
  quark: {
    code: 'quark',
    name: '夸克',
    accent: '#0b57d0',
    icon: '/platform-icons/quark.svg',
  },
  baiduai: {
    code: 'baiduai',
    name: '百度 AI+',
    accent: '#2932e1',
    icon: '/platform-icons/baiduai.svg',
  },
  weibo_zhisou: {
    code: 'weibo_zhisou',
    name: '微博智搜',
    accent: '#ff8200',
    icon: '/platform-icons/weibo_zhisou.svg',
  },
  wenxinyiyan: {
    code: 'wenxinyiyan',
    name: '文心一言',
    accent: '#2b6de5',
    icon: '/platform-icons/wenxinyiyan.svg',
  },
}

export const platformLabelMap: Record<string, string> = Object.fromEntries(
  Object.values(PLATFORM_META).map(item => [item.code, item.name]),
)

export function getPlatformMeta(code: string): PlatformMeta {
  const text = String(code || '').trim()
  if (PLATFORM_META[text]) return PLATFORM_META[text]
  const base = text.replace(/_mobile$/, '')
  if (PLATFORM_META[base]) {
    return { ...PLATFORM_META[base], code: text, name: platformLabelMap[text] || PLATFORM_META[base].name }
  }
  return {
    code: text,
    name: platformLabelMap[text] || text,
    accent: '#5b7aa8',
    icon: '',
  }
}

export const supportedPlatforms = [
  'deepseek',
  'doubao',
  'yuanbao',
  'kimi',
  'qianwen',
  'quark',
  'baiduai',
  'weibo_zhisou',
  'doubao_mobile',
  'deepseek_mobile',
].map(code => getPlatformMeta(code))

export function platformAccentColor(code: string) {
  return getPlatformMeta(code).accent
}
