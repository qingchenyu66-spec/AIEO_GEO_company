# Diagnosis Rank Chart Palette Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the desktop diagnosis report's embedded average-ranking trend chart with a high-contrast, line-style-distinct version while preserving all data.

**Architecture:** Extract the target chart's embedded PNG location from the standalone HTML, redraw the chart from the documented values using Matplotlib, and replace only that Base64 image payload. Verify the HTML delta, browser rendering, and PDF output.

**Tech Stack:** Python 3, Matplotlib, static HTML/Base64 PNG, Playwright Chromium.

## Global Constraints

- Modify only `C:\Users\Administrator\Desktop\周期报告样例_环比预览\售前诊断报告_改版.html`.
- Preserve the four series values and three date labels exactly.
- Use colors `#0057D9`, `#F28E2B`, `#009E73`, and `#C43C92`.
- Use distinct solid, short-dash, dash-dot, and long-dash line styles with circle, square, triangle, and diamond markers.
- Do not modify project business code or any other report chart.

---

### Task 1: Redraw and replace the target chart

**Files:**
- Modify: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\售前诊断报告_改版.html`
- Read: `C:\Users\Administrator\Desktop\周期报告样例_环比预览\_backup_20260713\售前诊断报告_改版.html`

**Interfaces:**
- Consumes: Existing `<div class="chart-title">平均排名趋势图</div>` followed by one Base64 PNG.
- Produces: A PNG with the same chart title, dates, values, reversed rank axis, and new visual encoding.

- [ ] **Step 1: Back up the current modified preview and record its hash**

Copy the HTML to `_backup_20260713\售前诊断报告_改版_高对比配色前.html` and verify the SHA-256 values match.

- [ ] **Step 2: Verify the chart currently lacks the new palette marker**

Decode the PNG immediately following `平均排名趋势图`; assert its binary payload does not equal the newly rendered image hash.

- [ ] **Step 3: Render the replacement chart**

Use these exact series:

```python
dates = ['06-30', '07-01', '07-02']
series = {
    '艾迪亚控股集团有限公司': ([2.4, 2.3, 2.4], '#0057D9', '-', 'o', 3.5),
    '分众传媒': ([3.2, 3.4, 3.2], '#F28E2B', (0, (4, 2)), 's', 2.5),
    '白马户外媒体': ([3.5, 5.0, 5.1], '#009E73', '-.', '^', 2.5),
    '华铁传媒': ([3.7, 4.4, 4.2], '#C43C92', (0, (8, 3)), 'D', 2.5),
}
```

Render at 1600x720 equivalent resolution, reverse the Y axis, label each point in its series color, keep a white background, and place the legend in the upper-right without covering data.

- [ ] **Step 4: Replace only the target Base64 payload**

Locate the first `<img src="data:image/png;base64,...">` after `<div class="chart-title">平均排名趋势图</div>` and replace only its Base64 content. Leave all surrounding HTML and all other Base64 images unchanged.

- [ ] **Step 5: Verify the HTML delta**

Assert:

- exactly one Base64 image changed;
- `AI 回答摘录` remains absent;
- `competitor-management-summary` remains present;
- all four visible report HTML files still exist.

### Task 2: Browser and PDF verification

**Files:**
- Read: Modified desktop diagnosis HTML.
- Create: `D:\py代码\GEO优化\tmp\pdfs\report-preview-checks\diagnosis-rank-chart-high-contrast.png`
- Create: `D:\py代码\GEO优化\tmp\pdfs\report-preview-checks\diagnosis-high-contrast.pdf`

**Interfaces:**
- Consumes: Updated desktop HTML.
- Produces: Browser screenshot and PDF proof.

- [ ] **Step 1: Serve the desktop folder over localhost and open it with Playwright**

Use a loopback-only HTTP server and a 1440x1000 viewport.

- [ ] **Step 2: Capture the target chart**

Capture the chart container whose title is `平均排名趋势图` and verify four visually distinct colors, line styles, and markers.

- [ ] **Step 3: Export and render PDF**

Export the updated diagnosis report to PDF, render the page containing the chart, and verify no clipping, overlap, blank page, or unreadable legend.

- [ ] **Step 4: Stop the temporary server and report the desktop preview path**

Confirm the rollback backup path and state that project business code was not modified.

