# Production Report Competitor Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将已确认的竞品展示、风险分级、实际执行时间和运营建议正式接入诊断报告及周/月/季度报告，同时让样例生成脚本与线上导出保持一致。

**Architecture:** 新增一个纯函数型竞品视觉与分析服务，统一实体颜色、线型、标记、排名风险和规则化运营结论；诊断报告复用该服务渲染逐次执行趋势和竞品模块，周期报告将同一分析结构写入 report modules，再由 Premium HTML/Word/PDF 导出链路消费。样例脚本只复用相同规则或同构纯函数，不改变任务调度、采集和非竞品报告模块。

**Tech Stack:** Python 3、FastAPI 服务层、Jinja2、Matplotlib、ECharts、pytest、现有 HTML→Word/PDF 导出链路。

## Global Constraints

- 只修改本计划列出的报告相关文件；保留工作区内其他未跟踪文件和用户改动。
- 诊断报告按真实执行批次展示，同一天三次执行必须保留三条数据；周报、月报、季度报告不改变原有周期聚合口径。
- 颜色不是唯一编码：折线同时使用不同线型与点形，表格同时显示风险文字/徽标。
- 竞品结论先由可验证规则生成；可选大模型只能润色文字，不能补造指标、公司或排名。
- 不修改报告任务调度、数据库表结构、API 请求结构和非竞品报告章节。
- 每个任务完成后只暂存该任务涉及的文件，禁止使用 `git add .`。

---

### Task 1: 建立统一竞品视觉与排名风险规则

**Files:**
- Create: `backend/app/services/report_competitor_visuals.py`
- Create: `backend/tests/test_report_competitor_visuals.py`

**Step 1: Write the failing tests**

在 `backend/tests/test_report_competitor_visuals.py` 覆盖以下行为：

```python
def test_known_entities_have_fixed_distinct_styles() -> None:
    styles = [entity_visual_style(name, brand_name="艾迪亚控股集团有限公司") for name in (
        "艾迪亚控股集团有限公司", "分众传媒", "白马户外媒体", "华铁传媒",
    )]
    assert [item.color for item in styles] == ["#0057D9", "#F28E2B", "#009E73", "#C43C92"]
    assert len({(item.line_style, item.marker) for item in styles}) == 4


def test_unknown_entity_style_is_deterministic() -> None:
    assert entity_visual_style("未知竞品A") == entity_visual_style("未知竞品A")
    assert entity_visual_style("未知竞品A") != entity_visual_style("未知竞品B")


@pytest.mark.parametrize(("rank", "level"), [
    (1, "good"), (3, "good"), (3.1, "watch"), (5, "watch"),
    (6, "warning"), (7, "warning"), (8, "danger"), (None, "neutral"),
])
def test_rank_risk_boundaries(rank: float | None, level: str) -> None:
    assert classify_rank_risk(rank).level == level
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_report_competitor_visuals.py -q`

Expected: FAIL because `report_competitor_visuals` does not exist.

**Step 3: Implement the pure service**

实现不可变数据类和纯函数：

```python
@dataclass(frozen=True)
class EntityVisualStyle:
    color: str
    line_style: str
    marker: str
    css_dash: str


@dataclass(frozen=True)
class RankRisk:
    level: Literal["good", "watch", "warning", "danger", "neutral"]
    label: str
    color: str


def entity_visual_style(entity_name: str, *, brand_name: str | None = None) -> EntityVisualStyle:
    normalized_name = normalize_entity_name(entity_name)
    return resolve_known_or_hashed_style(normalized_name, brand_name=brand_name)


def classify_rank_risk(rank: Any) -> RankRisk:
    return resolve_rank_risk(normalize_optional_rank(rank))
```

固定映射采用已确认色值；未知实体使用 `hashlib.sha256(normalized_name.encode("utf-8"))` 在备用样式表中稳定取模，禁止使用进程随机化的内置 `hash()`。排名边界为 `<=3` 绿色、`(3,5]` 黄色、`(5,7]` 橙色、`>7` 红色，空值为中性灰。

**Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_report_competitor_visuals.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/report_competitor_visuals.py backend/tests/test_report_competitor_visuals.py
git commit -m "feat: centralize competitor report visuals"
```

### Task 2: 让诊断趋势严格保留真实执行批次

**Files:**
- Modify: `backend/app/services/lead_diagnosis_analytics.py:206-425`
- Modify: `backend/tests/test_lead_diagnosis_analytics.py:75-135`
- Modify: `backend/tests/test_report_molizhishu.py:121-186`

**Step 1: Write the failing tests**

新增同一天三次运行测试，输入 `2026-07-03 09:30`、`2026-07-03 14:00`、`2026-07-03 19:30`，断言：

```python
assert [row["schedule_label"] for row in result["rank_trend"]] == [
    "2026-07-03 09:30", "2026-07-03 14:00", "2026-07-03 19:30",
]
assert len(result["rank_trend"]) == 3
```

再添加回退顺序用例：`run.schedule_label` 为空时使用关联调度上下文的 `schedule_label`，再为空时使用 `GeoMonitorSubtask.updated_at` 格式化为 `%Y-%m-%d %H:%M`；全部缺失时返回 `时间数据缺失`，不能伪造整点。

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_lead_diagnosis_analytics.py backend/tests/test_report_molizhishu.py -q`

Expected: FAIL because `_group_rows_by_day` and `_build_prompt_round_trend` collapse execution labels to dates.

**Step 3: Implement execution-label grouping**

- 将 `_day_key_from_run` 重命名/重构为 `_execution_key_from_run`，保留完整时间标签。
- 将 `_group_rows_by_day` 改为按执行键分组，排序键优先解析 `%Y-%m-%d %H:%M`，其次 ISO datetime，无法解析时稳定保持输入顺序。
- `_build_prompt_round_trend` 不再把 `schedule_label` 截成前 10 位。
- `_build_date_prompt_matrix` 仍可按日期汇总其原有矩阵，但诊断趋势和排名变化表必须消费完整执行标签。
- 更新原先断言“same day aggregate”的测试名称和预期，避免周期报告口径被误改。

**Step 4: Run focused tests**

Run: `python -m pytest backend/tests/test_lead_diagnosis_analytics.py backend/tests/test_report_molizhishu.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/lead_diagnosis_analytics.py backend/tests/test_lead_diagnosis_analytics.py backend/tests/test_report_molizhishu.py
git commit -m "fix: preserve diagnosis execution timestamps"
```

### Task 3: 将统一视觉规则接入诊断图表和竞品表格

**Files:**
- Modify: `backend/app/services/report_chart_service.py:59-260`
- Modify: `backend/app/services/report_molizhishu_fragments.py:107-336`
- Modify: `backend/app/templates/report_molizhishu/styles.css:492-590`
- Modify: `backend/tests/test_report_chart_service.py`
- Modify: `backend/tests/test_report_molizhishu.py:187-240`

**Step 1: Write the failing tests**

- monkeypatch Matplotlib `Axes.plot`，断言 `build_entity_rank_trend_chart` 为四家公司传入四个不同的 `color`、`linestyle`、`marker`。
- 对 `render_competitor_landscape_table` 断言每行含 `data-entity-color`、风险 class（如 `rank-risk-good`）和可见风险标签。
- 对提及率进度条断言不同公司不再统一使用蓝色。

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_report_chart_service.py backend/tests/test_report_molizhishu.py -q`

Expected: FAIL because chart/table/progress bars still use shared blue-centric styling.

**Step 3: Implement chart and fragment integration**

- `build_entity_rank_trend_chart` 调用 `entity_visual_style`，设置 color、line style、marker；保留排名轴反转和数据标签。
- `render_progress_cell` 增加 `entity_name`/`brand_name` 参数，用 CSS 变量 `--entity-color` 渲染条形图。
- `render_competitor_landscape_table` 增加色块、角色、平均排名风险徽标；前三名为绿色，越靠后依次黄/橙/红。
- CSS 加入实体图例、风险徽标和打印样式；黑白打印时仍由文字标签和边框区分。

**Step 4: Run focused tests**

Run: `python -m pytest backend/tests/test_report_chart_service.py backend/tests/test_report_molizhishu.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/report_chart_service.py backend/app/services/report_molizhishu_fragments.py backend/app/templates/report_molizhishu/styles.css backend/tests/test_report_chart_service.py backend/tests/test_report_molizhishu.py
git commit -m "feat: distinguish competitors in diagnosis reports"
```

### Task 4: 增加竞品管理摘要和运营动作，并删除 AI 回答摘录

**Files:**
- Modify: `backend/app/services/report_competitor_visuals.py`
- Modify: `backend/app/services/report_molizhishu_context_service.py:90-320`
- Modify: `backend/app/services/report_molizhishu_fragments.py:314-405`
- Modify: `backend/app/templates/report_molizhishu/report.html:60-145`
- Modify: `backend/app/templates/report_molizhishu/styles.css`
- Modify: `backend/tests/test_report_competitor_visuals.py`
- Modify: `backend/tests/test_report_molizhishu.py`

**Step 1: Write the failing tests**

为纯分析函数定义并测试稳定结构：

```python
analysis = build_competitor_analysis(
    brand_name="艾迪亚控股集团有限公司",
    rows=[
        {"name": "艾迪亚控股集团有限公司", "avg_rank": 4.2, "mention_rate": 8.8, "is_brand": True},
        {"name": "分众传媒", "avg_rank": 1.4, "mention_rate": 93.8},
        {"name": "白马户外媒体", "avg_rank": 5.1, "mention_rate": 2.5},
    ],
)
assert analysis["brand_position"]["risk"]["level"] == "watch"
assert analysis["head_competitor"]["name"] == "分众传媒"
assert analysis["nearest_competitor"]["name"] == "白马户外媒体"
assert analysis["actions"]
```

HTML 测试断言包含“竞争格局摘要”“建议动作”“风险说明”，且不包含“AI 回答摘录”和 `excerpt-card`。

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_report_competitor_visuals.py backend/tests/test_report_molizhishu.py -q`

Expected: FAIL because the analysis builder and new sections do not exist and excerpts remain.

**Step 3: Implement rule-based analysis and rendering**

`build_competitor_analysis` 输出 JSON-safe dict：`tiers`、`brand_position`、`head_competitor`、`nearest_competitor`、`gap_to_head`、`defend_target`、`chase_target`、`management_summary`、`actions`。规则只使用输入行：

- 头部：平均排名 `<=3`；腰部：`(3,5]`；追赶：`>5`；无排名单列“数据不足”。
- 品牌与头部差距为 `brand_rank - head_rank`；最近竞品按绝对排名差选择。
- 品牌领先最近竞品时生成“守位”动作，落后时生成“追赶”动作。
- 动作至少覆盖“重点平台复盘”和“重点问题/语义词内容补强”；没有平台/问题数据时明确写“需结合平台明细确认”，不补造名称。

Context service 生成分析并交给新 fragment 渲染；模板在竞品表格后插入摘要、动作和风险图例。彻底移除 `answer_excerpts_html` 的 context 生成、模板区块及专属 CSS；底层采集数据可保留，避免扩大改动范围。

**Step 4: Run focused tests**

Run: `python -m pytest backend/tests/test_report_competitor_visuals.py backend/tests/test_report_molizhishu.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/report_competitor_visuals.py backend/app/services/report_molizhishu_context_service.py backend/app/services/report_molizhishu_fragments.py backend/app/templates/report_molizhishu/report.html backend/app/templates/report_molizhishu/styles.css backend/tests/test_report_competitor_visuals.py backend/tests/test_report_molizhishu.py
git commit -m "feat: add competitor strategy to diagnosis reports"
```

### Task 5: 将竞品模块接入周报、月报、季度报告和导出链路

**Files:**
- Modify: `backend/app/services/report_period_content_service.py:379-760`
- Modify: `backend/app/templates/report_premium/report.html`
- Modify: `backend/app/templates/report_premium/styles.css`
- Modify: `backend/tests/test_report_enrichment_service.py`
- Modify: `backend/tests/test_tenant_diagnosis_report.py`
- Modify: `backend/tests/test_report_period_service.py`

**Step 1: Write the failing tests**

- 对 weekly/monthly/quarterly 三类 modules 断言存在 `competitor_analysis`，字段结构与 Task 4 相同。
- 断言非竞品模块 `overview`、`sentiment`、`source_influence` 保持存在且既有值不变。
- 渲染测试断言 Premium HTML 包含竞品色标、管理摘要、运营动作和排名风险文字。
- Word/PDF 上下文测试断言所需文字字段完整，且模板缺少可选竞品数据时仍可导出。

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_report_enrichment_service.py backend/tests/test_tenant_diagnosis_report.py backend/tests/test_report_period_service.py -q`

Expected: FAIL because `competitor_analysis` is absent.

**Step 3: Extend report modules without changing existing cadence logic**

- 在 `build_report_modules` 中添加 `competitor_analysis`，数据来自现有 `competitor_names` 与 diagnosis/统计中真实可用的竞品行。
- `sanitize_report_modules_for_type` 允许 weekly/monthly/quarterly/diagnosis 使用该模块；annual 若现有流程可消费则兼容保留，否则不主动展示。
- Premium 模板增加竞品章节，复用相同 CSS 变量、风险 class 和文字动作；不重排现有非竞品章节。
- Word/PDF 继续走现有 HTML 模板和打印 CSS，增加 `break-inside: avoid`、固定图例尺寸、长公司名换行规则；不允许用户模板自由改变数据结构。

**Step 4: Run focused tests**

Run: `python -m pytest backend/tests/test_report_enrichment_service.py backend/tests/test_tenant_diagnosis_report.py backend/tests/test_report_period_service.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/report_period_content_service.py backend/app/templates/report_premium/report.html backend/app/templates/report_premium/styles.css backend/tests/test_report_enrichment_service.py backend/tests/test_tenant_diagnosis_report.py backend/tests/test_report_period_service.py
git commit -m "feat: add competitor analysis to periodic reports"
```

### Task 6: 同步正式样例生成脚本

**Files:**
- Modify: `backend/scripts/generate_period_comparison_samples.py:430-540,1435-1505,2270-2410`
- Create: `backend/tests/test_generate_period_comparison_samples.py`

**Step 1: Write the failing tests**

动态加载脚本中的纯渲染函数，断言：

- 同一天三条 `updated_at` 在诊断样例中生成三个时间标签。
- 四家公司图表 series 的颜色、线型、symbol 互不相同。
- `render_competitor_html` 输出管理摘要、运营动作和风险说明。
- 输出不含“AI 回答摘录”。

**Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_generate_period_comparison_samples.py -q`

Expected: FAIL because the script currently aggregates by `row.updated_at.date()` and uses old competitor markup.

**Step 3: Synchronize sample generation**

- 保留该脚本现有命令入口和数据查询，只替换诊断趋势聚合、ECharts series 样式和竞品 HTML。
- ECharts 使用与服务端一致的固定颜色、`lineStyle.type`、`symbol`；未知公司采用 SHA-256 稳定映射。
- 周/月/季度样例只增加竞品摘要和动作，不改变其他章节数据。
- 删除样例里的 AI 回答摘录区块。

该脚本当前为用户工作区中的未跟踪文件；执行本任务时只在用户已确认“样例生成脚本也纳入项目”的前提下暂存此文件，不暂存其他未跟踪文件。

**Step 4: Run focused test and regenerate previews**

Run: `python -m pytest backend/tests/test_generate_period_comparison_samples.py -q`

Expected: PASS.

Run: `python backend/scripts/generate_period_comparison_samples.py --help`

Expected: exit 0 and list the script's supported generation arguments. Then run its documented generation command against the existing local preview data and write outputs only to `C:\Users\Administrator\Desktop\周期报告样例_环比预览`.

**Step 5: Commit**

```bash
git add backend/scripts/generate_period_comparison_samples.py backend/tests/test_generate_period_comparison_samples.py
git commit -m "feat: sync competitor report sample generator"
```

### Task 7: 验证 HTML、Word、PDF 排版与回归

**Files:**
- Modify if required by observed defects only: `backend/app/templates/report_molizhishu/styles.css`
- Modify if required by observed defects only: `backend/app/templates/report_premium/styles.css`
- Modify if required by observed defects only: tests corresponding to the corrected renderer

**Step 1: Run the report-focused suite**

Run:

```bash
python -m pytest backend/tests/test_report_competitor_visuals.py backend/tests/test_lead_diagnosis_analytics.py backend/tests/test_report_chart_service.py backend/tests/test_report_molizhishu.py backend/tests/test_report_enrichment_service.py backend/tests/test_tenant_diagnosis_report.py backend/tests/test_report_period_service.py backend/tests/test_generate_period_comparison_samples.py -q
```

Expected: PASS.

**Step 2: Generate and inspect representative exports**

生成至少四份代表文件：诊断报告、周报、月报、季度报告；每类至少检查 HTML，诊断和一种周期报告额外检查 Word/PDF。

视觉验收清单：

- 同日三次诊断执行分别显示实际时间。
- 四家公司折线肉眼可明显区分，且图例与数据点一致。
- 竞品条形图每家公司颜色稳定；前三排名为绿色，后续黄/橙/红风险递增。
- 管理摘要、差距、守位/追赶目标、平台/问题动作均来自已有数据。
- AI 回答摘录不存在。
- PDF 无章节标题孤行、表格越界、图例截断、公司名覆盖或跨页错位。

**Step 3: Run the full backend suite and record baseline exception**

Run: `python -m pytest backend/tests -q`

Expected: 新增和相关测试全部通过。若仍仅出现已知的时间敏感基线失败 `test_submit_rejects_future_force_slot`，单独记录其完整输出并确认本次 diff 未触及对应调度逻辑；若出现任何新增失败，返回对应任务修复后重跑。

**Step 4: Inspect the final diff**

Run:

```bash
git status --short
git diff --check
git diff --stat HEAD~6..HEAD
```

Expected: `git diff --check` 无输出；提交只包含计划列出的报告文件和测试，其他用户未跟踪文件保持未暂存。

**Step 5: Commit any verified print-only correction**

仅当视觉检查确实发现并修复打印样式问题时执行：

```bash
git add backend/app/templates/report_molizhishu/styles.css backend/app/templates/report_premium/styles.css
git commit -m "fix: stabilize report export layout"
```
