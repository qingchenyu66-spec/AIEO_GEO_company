/** ECharts 按需加载，避免首屏打包完整 echarts。 */

import type { ECharts } from 'echarts/core'

export type EchartsRuntime = {
  init: typeof import('echarts/core').init
  getInstanceByDom: typeof import('echarts/core').getInstanceByDom
  graphic?: typeof import('echarts/core').graphic
}

type LoaderMode = 'dashboard' | 'diagnosis' | 'portal' | 'wordcloud' | 'matrix'

const runtimes: Partial<Record<LoaderMode, EchartsRuntime>> = {}
const loadPromises: Partial<Record<LoaderMode, Promise<EchartsRuntime>>> = {}

async function loadDashboardRuntime(): Promise<EchartsRuntime> {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ])
  core.use([
    charts.PieChart,
    charts.BarChart,
    components.TooltipComponent,
    components.LegendComponent,
    components.GridComponent,
    components.GraphicComponent,
    renderers.CanvasRenderer,
  ])
  return {
    init: core.init,
    getInstanceByDom: core.getInstanceByDom,
    graphic: core.graphic,
  }
}

async function loadDiagnosisRuntime(): Promise<EchartsRuntime> {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ])
  core.use([
    charts.BarChart,
    charts.LineChart,
    components.GridComponent,
    components.LegendComponent,
    components.TooltipComponent,
    renderers.CanvasRenderer,
  ])
  return { init: core.init, getInstanceByDom: core.getInstanceByDom }
}

async function loadPortalRuntime(): Promise<EchartsRuntime> {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ])
  core.use([
    charts.BarChart,
    charts.GaugeChart,
    charts.LineChart,
    charts.PieChart,
    components.GraphicComponent,
    components.GridComponent,
    components.LegendComponent,
    components.TooltipComponent,
    renderers.CanvasRenderer,
  ])
  return {
    init: core.init,
    getInstanceByDom: core.getInstanceByDom,
    graphic: core.graphic,
  }
}

async function loadMatrixChartsRuntime(): Promise<EchartsRuntime> {
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ])
  core.use([
    charts.BarChart,
    charts.HeatmapChart,
    components.GridComponent,
    components.TooltipComponent,
    components.VisualMapComponent,
    renderers.CanvasRenderer,
  ])
  return {
    init: core.init,
    getInstanceByDom: core.getInstanceByDom,
    graphic: core.graphic,
  }
}

async function loadWordCloudRuntime(): Promise<EchartsRuntime> {
  const [core, renderers] = await Promise.all([
    import('echarts/core'),
    import('echarts/renderers'),
    import('echarts-wordcloud'),
  ])
  core.use([renderers.CanvasRenderer])
  return { init: core.init, getInstanceByDom: core.getInstanceByDom }
}

const loaders: Record<LoaderMode, () => Promise<EchartsRuntime>> = {
  dashboard: loadDashboardRuntime,
  diagnosis: loadDiagnosisRuntime,
  portal: loadPortalRuntime,
  wordcloud: loadWordCloudRuntime,
  matrix: loadMatrixChartsRuntime,
}

export async function loadEchartsRuntime(mode: LoaderMode = 'dashboard'): Promise<EchartsRuntime> {
  if (runtimes[mode]) return runtimes[mode]!
  if (!loadPromises[mode]) {
    loadPromises[mode] = loaders[mode]().then(runtime => {
      runtimes[mode] = runtime
      return runtime
    })
  }
  return loadPromises[mode]!
}

export async function initChart(
  el: HTMLElement,
  mode: LoaderMode = 'dashboard',
): Promise<ECharts> {
  const runtime = await loadEchartsRuntime(mode)
  const existing = runtime.getInstanceByDom(el)
  if (existing) return existing
  return runtime.init(el)
}

export type { ECharts }
