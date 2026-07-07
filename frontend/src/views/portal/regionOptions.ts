export interface RegionOption {
  code: string
  name: string
  /** 拼音全拼、首字母等，用于搜索 */
  keywords?: string
}

export const regionOptions: RegionOption[] = [
  { code: '', name: '全部区域' },
  { code: '110000', name: '北京', keywords: 'beijing bj' },
  { code: '120000', name: '天津', keywords: 'tianjin tj' },
  { code: '130000', name: '河北', keywords: 'hebei hb' },
  { code: '140000', name: '山西', keywords: 'shanxi sx' },
  { code: '150000', name: '内蒙古', keywords: 'neimenggu nmg' },
  { code: '210000', name: '辽宁', keywords: 'liaoning ln' },
  { code: '220000', name: '吉林', keywords: 'jilin jl' },
  { code: '230000', name: '黑龙江', keywords: 'heilongjiang hlj' },
  { code: '310000', name: '上海', keywords: 'shanghai sh' },
  { code: '320000', name: '江苏', keywords: 'jiangsu js' },
  { code: '330000', name: '浙江', keywords: 'zhejiang zj' },
  { code: '340000', name: '安徽', keywords: 'anhui ah' },
  { code: '350000', name: '福建', keywords: 'fujian fj' },
  { code: '360000', name: '江西', keywords: 'jiangxi jx' },
  { code: '370000', name: '山东', keywords: 'shandong sd' },
  { code: '410000', name: '河南', keywords: 'henan hn' },
  { code: '420000', name: '湖北', keywords: 'hubei hub hb' },
  { code: '430000', name: '湖南', keywords: 'hunan hun' },
  { code: '440000', name: '广东', keywords: 'guangdong gd' },
  { code: '450000', name: '广西', keywords: 'guangxi gx' },
  { code: '460000', name: '海南', keywords: 'hainan hi' },
  { code: '500000', name: '重庆', keywords: 'chongqing cq' },
  { code: '510000', name: '四川', keywords: 'sichuan sc' },
  { code: '520000', name: '贵州', keywords: 'guizhou gz' },
  { code: '530000', name: '云南', keywords: 'yunnan yn' },
  { code: '540000', name: '西藏', keywords: 'xizang xz tibet' },
  { code: '610000', name: '陕西', keywords: 'shaanxi sn sx' },
  { code: '620000', name: '甘肃', keywords: 'gansu gs' },
  { code: '630000', name: '青海', keywords: 'qinghai qh' },
  { code: '640000', name: '宁夏', keywords: 'ningxia nx' },
  { code: '650000', name: '新疆', keywords: 'xinjiang xj' },
  { code: '710000', name: '台湾', keywords: 'taiwan tw' },
  { code: '810000', name: '香港', keywords: 'xianggang xg hk' },
  { code: '820000', name: '澳门', keywords: 'aomen am mo' },
]

export const selectableRegionOptions = regionOptions.filter(item => item.code)

export function regionLabel(code: string | null | undefined) {
  if (!code) return '全部区域'
  return regionOptions.find(item => item.code === code)?.name || code
}

export function regionLabels(codes: string[] | null | undefined): string {
  if (!codes?.length) return '全部区域'
  return codes
    .map(code => regionOptions.find(item => item.code === code)?.name || code)
    .join('、')
}

function regionSearchText(region: RegionOption): string {
  return `${region.name} ${region.code} ${region.keywords || ''}`.toLowerCase()
}

/** 按名称、编码、拼音关键词过滤省份列表。 */
export function filterRegionOptions(query: string): RegionOption[] {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return selectableRegionOptions
  return selectableRegionOptions.filter(region => regionSearchText(region).includes(normalized))
}
