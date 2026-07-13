import type { MonitorSummary } from '../../services/monitor'

export type FunctionalPageConfig = {
  title: string
  subtitle: string
  mode: string
  actions: string[]
  kpis: Array<{ label: string; value: string; note: string }>
}

export function buildFunctionalPage(
  code: string,
  summary: MonitorSummary | null,
  sourceTotalCount: number,
  sourceRankingLength: number,
  menuName?: string | null,
): FunctionalPageConfig {
  const common = {
    kpis: [
      { label: '监测任务', value: String(summary?.task_count || 0), note: `${summary?.subtask_count || 0} 个子任务` },
      { label: '品牌提及率', value: `${summary?.mention_rate || 0}%`, note: '真实返回统计' },
      { label: '平均排名', value: summary?.avg_rank ? String(summary.avg_rank) : '-', note: '越小越靠前' },
      { label: '信源数量', value: String(sourceTotalCount || sourceRankingLength), note: '可点击溯源' },
    ],
  }
  const map: Record<string, FunctionalPageConfig> = {
    'customer.batch': {
      title: '批量监控',
      subtitle: '按平台端配置定时巡检，客户只查看进度、结果和导出。',
      mode: 'tasks',
      actions: ['查看历史任务', '导出明细', '生成报告'],
      ...common,
    },
    'customer.geo': {
      title: 'GEO监测中心',
      subtitle: '按关键词、模型平台、推荐排名和历史检测查看真实监测结果。',
      mode: 'geo',
      actions: ['查看快照', '导出结果', '生成报告'],
      ...common,
    },
    'customer.links': {
      title: '信源分析',
      subtitle: '检查官网、商城、媒体和问答来源是否被 AI 引用。',
      mode: 'sources',
      actions: ['打开信源', '加入报告'],
      ...common,
    },
    'customer.diagnosis': {
      title: '品牌诊断',
      subtitle: '把健康分、竞品差距、引用短板和优化建议集中展示。',
      mode: 'diagnosis',
      actions: ['查看建议', '生成诊断报告'],
      ...common,
    },
    'customer.competitor': {
      title: '品牌洞察',
      subtitle: '对比本品牌与竞品在 AI 推荐列表中的提及率、首位提及率与情绪趋势。',
      mode: 'competitor',
      actions: ['对比详情', '导出竞品报告'],
      ...common,
    },
    'customer.sources': {
      title: '信源分析',
      subtitle: '汇总 AI 回答中的引用来源，分析官网占比、媒体结构与高频站点。',
      mode: 'sources',
      actions: ['打开信源', '导出信源'],
      ...common,
    },
    'customer.reports': {
      title: '报告中心',
      subtitle: '预览报告结论、图表、明细和建议，可导出 PDF / Word。',
      mode: 'report',
      actions: ['预览报告', '导出 PDF', '导出 Word'],
      ...common,
    },
    'customer.knowledge': {
      title: '企业知识库',
      subtitle: '归档品牌白皮书、产品手册等资料，供监测报告引用与团队共享。',
      mode: 'knowledge',
      actions: ['上传资料', '查看归档'],
      ...common,
    },
    'platform.competitor': { title: '品牌洞察', subtitle: '运营端查看企业品牌与竞品在 AI 推荐中的提及率、排名、情绪趋势。', mode: 'competitor', actions: ['导出报告', '查看差距'], ...common },
    'platform.sources': { title: '信源分析', subtitle: '运营端查看企业各模型引用的信源结构、高频站点与可跳转原文。', mode: 'sources', actions: ['导出信源', '加入报告'], ...common },
    'platform.models': {
      title: '模型平台',
      subtitle: '平台目录同步自模力指数官方文档，展示今日各平台探测成功/失败条数。',
      mode: 'platforms',
      actions: [],
      kpis: [],
    },
    'platform.alerts': { title: '预警阈值', subtitle: '查看任务队列运行状态，并配置业务监测指标预警规则。', mode: 'alerts', actions: ['刷新监控', '查看规则'], ...common },
    'platform.snapshot_backfill': { title: '快照补录', subtitle: '抓取失败时粘贴 AI 分享链接与回答正文，自动重算排名并更新健康分。', mode: 'backfill', actions: ['提交补录'], ...common },
    'platform.reports': { title: '报告中心', subtitle: '预览与导出周期/诊断报告；诊断仅运营内部使用，客户端仅展示已发布周期报告。', mode: 'report', actions: ['导出 PDF', '导出 HTML', '导出 Word'], ...common },
    'platform.logs': {
      title: '操作日志',
      subtitle: '审计用户、企业、任务、权限和导出操作。',
      mode: 'logs',
      actions: [],
      kpis: [],
    },
    'platform.settings': {
      title: '系统配置',
      subtitle: '基础参数、数据上传接口、菜单权限和安全策略。',
      mode: 'settings',
      actions: ['导出配置', '操作日志'],
      kpis: [],
    },
  }
  const page = map[code] || map['customer.realtime'] || {
    title: '功能页',
    subtitle: '',
    mode: 'default',
    actions: [],
    ...common,
  }
  if (menuName?.trim()) {
    return { ...page, title: menuName.trim() }
  }
  return page
}
