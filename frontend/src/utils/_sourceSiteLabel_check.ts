import {
  citationSourceDisplay,
  citationSourceSiteLabel,
  citationSourceTitle,
  type CitationSourceLike,
} from './sourceSiteLabel'

type Case = {
  name: string
  source: CitationSourceLike
  expectSite: string | null
  expectTitle?: string
}

const cases: Case[] = [
  {
    name: 'docin url → 豆丁网',
    source: { title: '户外广告白皮书', url: 'https://www.docin.com/p-1.html' },
    expectSite: '豆丁网',
  },
  {
    name: 'qcc url → 企查查',
    source: { title: '企业信息', url: 'https://www.qcc.com/firm/1' },
    expectSite: '企查查',
  },
  {
    name: '标题末尾 -BOSS直聘 → 去重',
    source: { title: '招聘-BOSS直聘', url: 'https://www.zhipin.com/job/1' },
    expectSite: null,
  },
  {
    name: '标题末尾 ->买购APP site → 去重',
    source: { title: '行业榜单->买购APP', site: '买购APP' },
    expectSite: null,
  },
  {
    name: '标题仅提及站名话题，仍应显示后缀',
    source: { title: '知乎回答精选合集', url: 'https://zhuanlan.zhihu.com/p/123' },
    expectSite: '知乎',
  },
  {
    name: '无 url/site → 无后缀',
    source: { title: '仅有标题无链接' },
    expectSite: null,
  },
  {
    name: '中文 site 优先于 url',
    source: {
      title: '某篇文章',
      site: '企查查',
      url: 'https://www.docin.com/p-2.html',
    },
    expectSite: '企查查',
  },
  {
    name: 'url 为标题文本（非 http）→ 无后缀',
    source: {
      title: '户外传媒品牌前十 户外传媒行业10大品牌名录2026->买购APP',
      url: '户外传媒品牌前十 户外传媒行业10大品牌名录2026->买购APP',
    },
    expectSite: null,
  },
  {
    name: '标题已含买购APP 且 url 也是 maigoo → 去重',
    source: {
      title: '户外传媒品牌前十->买购APP',
      url: 'https://www.maigoo.com/brand/1.html',
    },
    expectSite: null,
  },
  {
    name: '裸域名 site + 有 url → 用映射站名',
    source: {
      title: '白皮书 PDF',
      site: 'docin.com',
      url: 'https://www.docin.com/p-9.html',
    },
    expectSite: '豆丁网',
  },
  {
    name: '未知域名 → 展示 hostname',
    source: {
      title: '行业资讯',
      url: 'https://news.example.org/a/1',
    },
    expectSite: 'news.example.org',
  },
  {
    name: '子域名命中映射',
    source: {
      title: '一篇专栏文章',
      url: 'https://zhuanlan.zhihu.com/p/123',
    },
    expectSite: '知乎',
  },
  {
    name: '标题含 hostname 英文 → 去重',
    source: {
      title: 'see zhihu.com discussion',
      url: 'https://www.zhihu.com/question/1',
    },
    expectSite: null,
  },
  {
    name: 'site=example 短英文品牌（测试夹具形态）',
    source: {
      title: '行业报告',
      site: 'example',
      url: 'https://example.com/ads-report',
    },
    expectSite: 'example',
  },
  {
    name: '空对象标题兜底',
    source: {},
    expectSite: null,
    expectTitle: '未命名信源',
  },
  {
    name: '截图样例：BOSS 标题无 url',
    source: { title: '「大象广告有限责任公司招聘」-BOSS直聘' },
    expectSite: null,
    expectTitle: '「大象广告有限责任公司招聘」-BOSS直聘',
  },
]

let failed = 0
for (const item of cases) {
  const got = citationSourceSiteLabel(item.source)
  const title = citationSourceTitle(item.source)
  const display = citationSourceDisplay(item.source)
  const siteOk = got === item.expectSite
  const titleOk = item.expectTitle == null || title === item.expectTitle
  const displayOk = display.title === title && display.site === got
  if (!siteOk || !titleOk || !displayOk) {
    failed += 1
    console.error('FAIL', item.name, { got, expectSite: item.expectSite, title, expectTitle: item.expectTitle, display })
  } else {
    console.log('OK  ', item.name, '→', got === null ? '(无后缀)' : `· ${got}`)
  }
}

if (failed) {
  throw new Error(`sourceSiteLabel self-check: ${failed} failed`)
}
console.log(`sourceSiteLabel self-check ok (${cases.length} cases)`)
