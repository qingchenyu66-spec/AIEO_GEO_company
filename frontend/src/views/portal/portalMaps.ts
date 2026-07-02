export {
  platformLabelMap,
  supportedPlatforms,
  getPlatformMeta,
  platformAccentColor,
} from './platformMeta'

export {
  comparePlatformCodes,
  platformMarketRank,
  sortPlatformCodes,
  sortPlatformRows,
  sortPlatformTabs,
  formatPlatformLabels,
} from './platformOrder'

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
