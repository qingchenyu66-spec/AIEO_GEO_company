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
    'customer.sentiment': {
      title: '舆情监控',
      subtitle: '查看 AI 在介绍与评价品牌时的正负面倾向，定位风险内容并导出报告。',
      mode: 'sentiment',
      actions: ['查看负面内容', '导出舆情报告'],
      kpis: [
        { label: '口碑样本', value: '-', note: '仅口碑类问题' },
        { label: '正面占比', value: '-', note: '有效情感样本' },
        { label: '负面占比', value: '-', note: '待关注内容' },
        { label: '负面条数', value: '-', note: '可导出明细' },
      ],
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
      title: '竞品分析',
      subtitle: '按提及率、平均排名、信源数量和曝光差距对比竞品。',
      mode: 'competitor',
      actions: ['对比详情', '导出竞品报告'],
      ...common,
    },
    'customer.sources': {
      title: '信源分析',
      subtitle: '查看信源质量、原文链接和网页快照。',
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
      subtitle: '客户侧仅允许上传文章类文件，平台端可查看各公司上传记录。',
      mode: 'knowledge',
      actions: ['上传 PDF / Word', '查看文件记录'],
      ...common,
    },
    'platform.plans': { title: '套餐额度', subtitle: '按企业查看接口消耗、额度余量和预警阈值。', mode: 'platform', actions: ['导出额度', '查看消耗'], ...common },
    'platform.admins': { title: '管理员账号', subtitle: '平台管理员、职位分配、权限配置和安全状态。', mode: 'platform', actions: ['新增管理员', '分配权限'], ...common },
    'platform.sentiment': { title: '舆情监控', subtitle: '运营端统一查看企业正负面内容、词云、处置依据和专项报告。', mode: 'sentiment', actions: ['导出舆情', '生成专项报告'], ...common },
    'platform.competitor': { title: '竞品分析', subtitle: '按企业品牌和竞品库做提及率、排名、来源和口碑对标。', mode: 'competitor', actions: ['导出竞品报告', '查看差距'], ...common },
    'platform.sources': { title: '信源分析', subtitle: '查看各模型信源、来源质量、跳转链接和快照证据。', mode: 'sources', actions: ['导出信源', '加入报告'], ...common },
    'platform.diagnosis': { title: '品牌诊断', subtitle: '运营人员选择企业和模型平台后，基于监测结果生成诊断依据与建议。', mode: 'diagnosis', actions: ['保存诊断', '生成报告'], ...common },
    'platform.models': { title: '模型平台', subtitle: '维护支持平台、移动端平台、模式和可用状态。', mode: 'platforms', actions: ['导出平台', '查看状态'], ...common },
    'platform.alerts': { title: '预警阈值', subtitle: '配置排名下滑、负面占比、失败率和额度预警。', mode: 'platform', actions: ['导出规则', '查看日志'], ...common },
    'platform.reports': { title: '报告中心', subtitle: '运营端生成、预览、编辑并导出客户报告。', mode: 'report', actions: ['生成预览', '导出 PDF', '导出 Word'], ...common },
    'platform.logs': { title: '操作日志', subtitle: '审计用户、企业、任务、权限和导出操作。', mode: 'logs', actions: ['导出日志', '筛选操作'], ...common },
    'platform.settings': { title: '系统配置', subtitle: '基础参数、数据上传接口、菜单权限和安全策略。', mode: 'settings', actions: ['导出配置', '操作日志'], ...common },
  }
  return map[code] || map['customer.realtime'] || {
    title: '功能页',
    subtitle: '',
    mode: 'default',
    actions: [],
    ...common,
  }
}
