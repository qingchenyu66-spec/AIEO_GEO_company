# Report Preview Competitor Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update four desktop HTML report previews so the diagnosis report shows per-execution timestamps and omits AI excerpts, while all reports provide a richer, consistently colored competitor analysis with rank-risk warnings.

**Architecture:** Treat the desktop HTML files as standalone delivery artifacts. Back them up before editing, apply shared CSS and static content directly inside each HTML file, preserve all non-target sections, then validate structure with deterministic text checks and validate layout by browser/PDF rendering.

**Tech Stack:** Static HTML/CSS/JavaScript, ECharts 5.5.1 already bundled in the preview folder, Playwright/Chromium for PDF rendering, PowerShell for deterministic validation.

## Global Constraints

- Do not modify project business code, database schema, report generator, production templates, or scheduling logic.
- Modify only the four target HTML files under `C:\Users\Administrator\Desktop\周期报告样例_环比预览`.
- The diagnosis report alone receives timestamp splitting and AI excerpt removal.
- Weekly, monthly, and quarterly reports receive competitor-section changes only.
- Brand identity colors remain stable across every report and chart.
- Rank risk thresholds are exactly: 1-3 green, 4-5 yellow, 6-7 orange, 8+ red.
- Missing source data must display `当前样本暂不足` or `时间数据缺失`; never fabricate data.
- Browser/PDF output must have no clipped text, chart overflow, unexpected blank pages, or broken section pagination.

---

### Task 1: Create backups and baseline assertions

**Files:**
- Read: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\售前诊断报告_改版.html`
- Read: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\艾迪亚控股集团有限公司_周报_环比样例_20260629_V2.html`
- Read: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\艾迪亚控股集团有限公司_月报_环比样例_20260601_V2.html`
- Read: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\艾迪亚控股集团有限公司_季报_环比样例_20260401_V2.html`
- Create: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\_backup_20260713\<same filenames>`

**Interfaces:**
- Consumes: Existing standalone HTML previews.
- Produces: Byte-identical rollback copies and baseline hashes for later comparison.

- [ ] **Step 1: Verify all target files exist**

```powershell
$root = 'C:\Users\Administrator\Desktop\周期报告样例_环比预览'
$files = @(
  '售前诊断报告_改版.html',
  '艾迪亚控股集团有限公司_周报_环比样例_20260629_V2.html',
  '艾迪亚控股集团有限公司_月报_环比样例_20260601_V2.html',
  '艾迪亚控股集团有限公司_季报_环比样例_20260401_V2.html'
)
$files | ForEach-Object {
  if (-not (Test-Path -LiteralPath (Join-Path $root $_))) { throw "Missing: $_" }
}
```

Expected: Command exits successfully without output.

- [ ] **Step 2: Create byte-identical backups**

```powershell
$backup = Join-Path $root '_backup_20260713'
New-Item -ItemType Directory -Force -Path $backup | Out-Null
$files | ForEach-Object {
  Copy-Item -LiteralPath (Join-Path $root $_) -Destination (Join-Path $backup $_) -Force
}
```

Expected: Four files exist in `_backup_20260713`.

- [ ] **Step 3: Verify backup hashes**

```powershell
$files | ForEach-Object {
  $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root $_)).Hash
  $backupHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $backup $_)).Hash
  if ($sourceHash -ne $backupHash) { throw "Backup mismatch: $_" }
}
```

Expected: Command exits successfully without output.

- [ ] **Step 4: Record baseline section counts**

```powershell
$files | ForEach-Object {
  $text = Get-Content -Raw -LiteralPath (Join-Path $root $_)
  [pscustomobject]@{
    File = $_
    Sections = ([regex]::Matches($text, '<section\b')).Count
    CompetitorSections = ([regex]::Matches($text, 'id="competitors"')).Count
    AiExcerpts = ([regex]::Matches($text, 'AI 回答摘录')).Count
  }
}
```

Expected: Each periodic report has one competitor section; diagnosis contains one `AI 回答摘录` heading before modification.

### Task 2: Update the diagnosis preview

**Files:**
- Modify: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\售前诊断报告_改版.html:883`
- Modify: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\售前诊断报告_改版.html:903`
- Modify: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\售前诊断报告_改版.html:1027`

**Interfaces:**
- Consumes: Existing static competitor metrics, ranking tables, chart images, and any timestamp strings already present in the HTML.
- Produces: `competitor-management-summary`, `competitor-operation-detail`, `rank-risk-*`, and `entity-*` HTML classes; per-execution timestamp rows; no AI excerpt section.

- [ ] **Step 1: Write failing structural checks**

```powershell
$file = 'C:\Users\Administrator\Desktop\周期报告样例_环比预览\售前诊断报告_改版.html'
$html = Get-Content -Raw -LiteralPath $file
$checks = @(
  @{ Name='AI excerpt removed'; Pass=($html -notmatch 'AI 回答摘录') },
  @{ Name='Management summary present'; Pass=($html -match 'competitor-management-summary') },
  @{ Name='Operation detail present'; Pass=($html -match 'competitor-operation-detail') },
  @{ Name='Risk legend present'; Pass=($html -match '1-3.*优势' -and $html -match '8.*高风险') },
  @{ Name='Execution time header present'; Pass=($html -match '执行时间') }
)
$checks | Where-Object { -not $_.Pass }
```

Expected before editing: All five checks are reported as failing.

- [ ] **Step 2: Add shared identity and risk CSS**

Insert CSS before the closing `</style>`:

```css
.competitor-management-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:14px 0}
.competitor-summary-card{border:1px solid #d7e3f2;border-radius:12px;padding:14px;background:#f8fbff}
.competitor-summary-card strong{display:block;color:#123a63;font-size:18px;margin-top:5px}
.competitor-operation-detail{margin:14px 0;padding:16px;border:1px solid #d7e3f2;border-radius:12px;background:#fff}
.competitor-reading-note{padding:12px 14px;border-left:4px solid #2563eb;background:#eff6ff;color:#334155;line-height:1.75}
.competitor-legend{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.competitor-legend span,.rank-risk{display:inline-block;border-radius:999px;padding:3px 9px;font-weight:700;font-size:12px}
.rank-risk-good{color:#166534;background:#dcfce7}.rank-risk-watch{color:#854d0e;background:#fef3c7}
.rank-risk-warning{color:#9a3412;background:#ffedd5}.rank-risk-danger{color:#991b1b;background:#fee2e2}
.entity-aidiya{color:#2563eb}.entity-fenzhong{color:#f97316}.entity-youxhi{color:#8b5cf6}
.entity-baima{color:#06b6d4}.entity-huatie{color:#ec4899}.entity-degao{color:#14b8a6}
@media(max-width:900px){.competitor-management-summary{grid-template-columns:1fr 1fr}}
@media print{.competitor-management-summary,.competitor-operation-detail{break-inside:avoid;page-break-inside:avoid}}
```

- [ ] **Step 3: Add management summary and operating detail**

Immediately after the existing `竞品格局对比` heading, add:

```html
<div class="competitor-reading-note">
  本模块基于同周期 AI 推荐结果，对比本品牌与已配置竞品的提及率、平均推荐排名及变化趋势。排名数值越小表示推荐位置越靠前；Top3 为优势区间，4-5 名为关注区间，6-7 名为预警区间，8 名以后为高风险区间。企业颜色用于识别对象，排名风险色用于判断优化优先级；相关指标不等同于实际市场份额。
</div>
<div class="competitor-legend">
  <span class="rank-risk-good">1-3 优势</span><span class="rank-risk-watch">4-5 关注</span>
  <span class="rank-risk-warning">6-7 预警</span><span class="rank-risk-danger">8+ 高风险</span>
</div>
<div class="competitor-management-summary">
  <div class="competitor-summary-card">头部竞品<strong>分众传媒</strong><small>提及率 54.8%，当前竞争标杆</small></div>
  <div class="competitor-summary-card">本品牌位置<strong>追赶梯队</strong><small>提及率 27.8%，平均排名 4.8</small></div>
  <div class="competitor-summary-card">主要差距<strong>提及率 -27.0pp</strong><small>相对分众传媒</small></div>
  <div class="competitor-summary-card">优先任务<strong>冲击 Top3</strong><small>优先改善电梯广告语义词</small></div>
</div>
<div class="competitor-operation-detail">
  <h4>运营判断与建议</h4>
  <ul>
    <li>重点防守对象：分众传媒在提及率上领先，应持续跟踪其高频语义词和引用信源。</li>
    <li>优先追赶对象：德高中国提及率接近本品牌且平均排名更靠前，适合作为阶段追赶目标。</li>
    <li>突破方向：电梯广告语义词提及率不足 10%，优先补充案例、问答和权威媒体信源。</li>
    <li>平台动作：夸克、DeepSeek 为覆盖短板；微博智搜为现有优势阵地，需保持内容更新。</li>
  </ul>
</div>
```

- [ ] **Step 4: Apply entity colors and rank badges to competitor rows**

Wrap each company name with its stable class and wrap each average rank with the exact threshold class:

```html
<span class="entity-fenzhong">分众传媒</span>
<span class="rank-risk-watch">3.6</span>
<span class="entity-degao">德高中国</span>
<span class="rank-risk-watch">3.5</span>
<span class="entity-aidiya">★ 艾迪亚控股集团有限公司</span>
<span class="rank-risk-watch">4.8</span>
<span class="entity-huatie">华铁传媒</span>
<span class="rank-risk-good">1.9</span>
<span class="entity-youxhi">北京优视传媒</span>
<span class="rank-risk-warning">5.4</span>
<span class="entity-baima">白马户外媒体</span>
<span class="rank-risk-danger">7.8</span>
```

For decimal ranks, compare the numeric value directly to the integer boundaries; `3.6` falls in the 4-5 visual band because it is greater than 3, `5.4` falls in the 6-7 band because it is greater than 5, and `7.8` falls in the 8+ band because it is greater than 7.

- [ ] **Step 5: Replace daily aggregation labels with execution timestamps**

Inspect all timestamp-like values in the file:

```powershell
rg -o "20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?" $file | Sort-Object -Unique
```

If execution timestamps exist, change the trend table first column to `执行时间` and emit one existing record per timestamp, formatted `YYYY-MM-DD HH:mm`, sorted ascending. If only dates exist, change the first column to `执行时间` and append `（时间数据缺失）` to each existing date; do not invent three clock times.

- [ ] **Step 6: Remove the AI excerpt block**

Delete the containing block beginning with:

```html
<h3 class="overview-subtitle">AI 回答摘录</h3>
```

and ending after the final `excerpt-card`, preserving the following `采信网站概览` section.

- [ ] **Step 7: Run structural checks**

```powershell
$html = Get-Content -Raw -LiteralPath $file
if ($html -match 'AI 回答摘录') { throw 'AI excerpts still present' }
foreach ($token in @('competitor-management-summary','competitor-operation-detail','rank-risk-good','rank-risk-watch','rank-risk-warning','rank-risk-danger','执行时间')) {
  if ($html -notmatch [regex]::Escape($token)) { throw "Missing token: $token" }
}
```

Expected: Command exits successfully without output.

### Task 3: Update weekly, monthly, and quarterly competitor sections

**Files:**
- Modify: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\艾迪亚控股集团有限公司_周报_环比样例_20260629_V2.html:539`
- Modify: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\艾迪亚控股集团有限公司_月报_环比样例_20260601_V2.html:533`
- Modify: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\艾迪亚控股集团有限公司_季报_环比样例_20260401_V2.html:519`

**Interfaces:**
- Consumes: Existing competitor table data and ECharts `competitorRankTrendChart` series.
- Produces: Identical competitor information architecture and color mapping in all three periodic reports; unchanged non-competitor sections.

- [ ] **Step 1: Write failing section checks**

```powershell
$root = 'C:\Users\Administrator\Desktop\周期报告样例_环比预览'
$periodFiles = Get-ChildItem -LiteralPath $root -Filter '*V2.html'
$periodFiles | ForEach-Object {
  $html = Get-Content -Raw -LiteralPath $_.FullName
  foreach ($token in @('competitor-management-summary','competitor-operation-detail','rank-risk-danger','entity-fenzhong')) {
    if ($html -notmatch $token) { "FAIL $($_.Name): $token" }
  }
}
```

Expected before editing: Each file reports missing tokens.

- [ ] **Step 2: Add the shared competitor CSS to all three files**

Insert the same CSS classes from Task 2 Step 2 into each periodic report before `</style>`. Do not alter existing non-competitor selectors.

- [ ] **Step 3: Add management and operating content to each competitor section**

After each `<h2>竞品对比分析 · 环比上一周期</h2>`, add the common reading note and risk legend from Task 2. Build four summary cards using the metrics already present in that report's competitor table:

```html
<div class="competitor-management-summary">
  <div class="competitor-summary-card">竞争格局<strong>本品牌领先</strong><small>提及率与平均排名保持前列</small></div>
  <div class="competitor-summary-card">本品牌位置<strong>优势梯队</strong><small>平均排名进入或接近 Top3</small></div>
  <div class="competitor-summary-card">最接近竞品<strong>北京优视传媒</strong><small>优先监测其排名和提及率变化</small></div>
  <div class="competitor-summary-card">优先动作<strong>巩固 Top3</strong><small>针对报告已有最弱语义词和平台补强</small></div>
</div>
```

For the weekly file, add `本品牌提及率 61.6% / 平均排名 #3.0 / 相对北京优视传媒领先 9.1pp` to the card descriptions. For the monthly file, use `59.3% / #2.8 / 领先 1.6pp`. For the quarterly file, use `62.6% / #3.3 / 领先 4.3pp`. If any of these source values is absent during execution, use `当前样本暂不足` instead of introducing a replacement value.

- [ ] **Step 4: Add stable company colors to tables and ECharts**

Use this exact mapping everywhere:

```javascript
const COMPANY_COLORS = {
  '艾迪亚控股集团有限公司': '#2563eb',
  '分众传媒': '#f97316',
  '北京优视传媒': '#8b5cf6',
  '白马户外媒体': '#06b6d4',
  '华铁传媒': '#ec4899',
  '德高中国': '#14b8a6'
};
```

Change competitor ECharts series generation to:

```javascript
series: payload.series.map((s) => ({
  name: s.name,
  type: 'line',
  data: s.data,
  connectNulls: false,
  symbol: 'circle',
  symbolSize: s.is_brand ? 9 : 7,
  lineStyle: { width: s.is_brand ? 4 : 3, color: COMPANY_COLORS[s.name] || '#64748b' },
  itemStyle: { color: COMPANY_COLORS[s.name] || '#64748b' }
}))
```

Wrap table company names with the corresponding `entity-*` class and ranking values with the threshold badge class.

- [ ] **Step 5: Add report-cadence-specific operating recommendations**

Use existing report values and add one compact `competitor-operation-detail` block:

```html
<div class="competitor-operation-detail">
  <h3>竞品运营拆解</h3>
  <ul>
    <li><strong>重点防守：</strong>头部竞品及其领先指标。</li>
    <li><strong>优先追赶：</strong>与本品牌差距最小且排名更靠前的竞品。</li>
    <li><strong>平台突破：</strong>报告已有的最弱平台。</li>
    <li><strong>语义词突破：</strong>报告已有的最弱监控词。</li>
  </ul>
</div>
```

For weekly use `下周执行重点`; monthly use `下月运营重点`; quarterly use `下季度策略重点` in the block heading.

- [ ] **Step 6: Verify non-competitor sections stayed byte-identical in meaning**

Compare section heading sequences between backups and modified files:

```powershell
$backup = Join-Path $root '_backup_20260713'
$periodFiles | ForEach-Object {
  $old = Get-Content -Raw -LiteralPath (Join-Path $backup $_.Name)
  $new = Get-Content -Raw -LiteralPath $_.FullName
  $oldHeadings = [regex]::Matches($old, '<h2[^>]*>(.*?)</h2>') | ForEach-Object { $_.Groups[1].Value }
  $newHeadings = [regex]::Matches($new, '<h2[^>]*>(.*?)</h2>') | ForEach-Object { $_.Groups[1].Value }
  if (($oldHeadings -join '|') -ne ($newHeadings -join '|')) { throw "Heading sequence changed: $($_.Name)" }
}
```

Expected: Command exits successfully without output.

- [ ] **Step 7: Run periodic structural checks**

```powershell
$periodFiles | ForEach-Object {
  $html = Get-Content -Raw -LiteralPath $_.FullName
  foreach ($token in @('competitor-management-summary','competitor-operation-detail','rank-risk-good','rank-risk-watch','rank-risk-warning','rank-risk-danger','COMPANY_COLORS')) {
    if ($html -notmatch $token) { throw "Missing $token in $($_.Name)" }
  }
}
```

Expected: Command exits successfully without output.

### Task 4: Browser and PDF visual verification

**Files:**
- Read: All four modified desktop HTML files.
- Create: `D:\py代码\GEO优化\tmp\pdfs\report-preview-checks\*.pdf`
- Create: `D:\py代码\GEO优化\tmp\pdfs\report-preview-checks\*.png`

**Interfaces:**
- Consumes: Modified standalone HTML files.
- Produces: Visual evidence that browser and PDF output are readable and stable.

- [ ] **Step 1: Open each HTML in Chromium and check console errors**

Use Playwright with `file:///` URLs. For every report, wait until `document.fonts.ready`, wait 800 ms for ECharts, and assert no uncaught page errors occurred.

Expected: Four pages load; no fatal JavaScript error; competitor charts render where present.

- [ ] **Step 2: Capture full-page browser screenshots**

Write screenshots to:

```text
D:\py代码\GEO优化\tmp\pdfs\report-preview-checks\diagnosis-full.png
D:\py代码\GEO优化\tmp\pdfs\report-preview-checks\weekly-full.png
D:\py代码\GEO优化\tmp\pdfs\report-preview-checks\monthly-full.png
D:\py代码\GEO优化\tmp\pdfs\report-preview-checks\quarterly-full.png
```

Expected: Identity colors are distinguishable, rank badges follow thresholds, and no AI excerpt appears in diagnosis.

- [ ] **Step 3: Export PDFs using Chromium print**

Use A4 with print backgrounds enabled and the HTML's existing print CSS. Save stable filenames under `tmp/pdfs/report-preview-checks`.

Expected: Four non-empty PDF files.

- [ ] **Step 4: Render PDF pages to PNG**

```powershell
pdftoppm -png -r 140 'diagnosis.pdf' 'diagnosis-page'
pdftoppm -png -r 140 'weekly.pdf' 'weekly-page'
pdftoppm -png -r 140 'monthly.pdf' 'monthly-page'
pdftoppm -png -r 140 'quarterly.pdf' 'quarterly-page'
```

Expected: One PNG per PDF page. If `pdftoppm` is unavailable, use the workspace Poppler binary discovered via `codex_app__load_workspace_dependencies`.

- [ ] **Step 5: Inspect all pages containing competitor content**

Check these exact conditions visually:

- Summary cards do not clip or overlap.
- Company colors match across table, chart, and legend.
- Green/yellow/orange/red risk badges remain legible in print.
- ECharts legends do not overflow.
- The diagnosis timestamp table is readable.
- Removing AI excerpts did not leave an unexpected blank page.
- The next section begins cleanly after competitor content.

Expected: Zero visible layout defects. If any defect exists, adjust only target-section CSS and repeat Steps 1-5.

- [ ] **Step 6: Run final deterministic acceptance checks**

```powershell
$diagnosis = Get-Content -Raw -LiteralPath (Join-Path $root '售前诊断报告_改版.html')
if ($diagnosis -match 'AI 回答摘录') { throw 'Diagnosis still includes AI excerpts' }
if ($diagnosis -notmatch '执行时间') { throw 'Diagnosis lacks execution-time label' }
$files | ForEach-Object {
  $html = Get-Content -Raw -LiteralPath (Join-Path $root $_)
  foreach ($token in @('competitor-management-summary','rank-risk-good','rank-risk-danger')) {
    if ($html -notmatch $token) { throw "Acceptance failure $token: $_" }
  }
}
```

Expected: Command exits successfully without output.

### Task 5: Deliver preview locations and rollback instructions

**Files:**
- Read: Modified desktop HTML files.
- Read: `_backup_20260713` rollback files.

**Interfaces:**
- Consumes: Verified desktop previews and backups.
- Produces: Clear handoff with links to preview files and an exact rollback procedure.

- [ ] **Step 1: Report changed artifacts**

Provide clickable absolute paths for all four modified HTML files and state explicitly that project business code was not changed.

- [ ] **Step 2: Report timestamp-data limitation truthfully**

If actual execution timestamps were absent from the static diagnosis HTML, state that the preview marks the data as missing and that true per-run timestamps require regeneration from source task data. Do not claim that fabricated time rows are actual execution times.

- [ ] **Step 3: Provide rollback command**

```powershell
$root = 'C:\Users\Administrator\Desktop\周期报告样例_环比预览'
$backup = Join-Path $root '_backup_20260713'
Get-ChildItem -LiteralPath $backup -Filter '*.html' | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $root $_.Name) -Force
}
```

Expected: All four previews can be restored exactly from their backups.
