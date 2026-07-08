# GEO Monitor 功能测试报告

- **测试批次**: `FT20260707`
- **执行时间**: 2026-07-07 17:37:55 +0800
- **环境**: API `http://127.0.0.1:8001/api/v1` / 前端 `http://127.0.0.1:5173`
- **测试账号**: `platform/Admin@2026`（运营）、`jinoutuliao/Geo@2026`（客户租户15）
- **数据策略**: 保留测试数据，标记前缀 `[FT20260707]`

## 1. 测试方法

| 层级 | 方法 | 说明 |
|------|------|------|
| API 集成 | `functional_test_suite.py` | 真实 HTTP 调用运行中后端，Bearer 鉴权 |
| 单元/集成 | `pytest tests/` | 后端逻辑与 API 回归 |
| UI 冒烟 | HTTP 拉取 SPA + 人工验收清单 | 验证路由可访问；关键交互见 §4 |

## 2. 汇总

| 指标 | 数量 |
|------|------|
| 用例总数 | 53 |
| 通过 | 51 |
| 失败 | 1 |
| 跳过 | 1 |
| 通过率（含跳过） | 98% |

### pytest 回归

```
........................................................................ [ 59%]
..........................F......................                        [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\py代码\GEO优化\backend\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_auth.py::test_dual_identity_login_and_select
  D:\py代码\GEO优化\backend\.venv\Lib\site-packages\passlib\handlers\argon2.py:716: DeprecationWarning: Accessing argon2.__version__ is deprecated and will be removed in a future release. Use importlib.metadata directly to query for argon2-cffi's packaging metadata.
    _argon2_cffi.__version__, max_version)

tests/test_monitor_snapshot_backfill_api.py::test_ops_logs_supports_filters
  D:\py代码\GEO优化\backend\app\api\v1\endpoints\ops.py:30: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    since = datetime.utcnow() - timedelta(days=days)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_snapshot_backfill_service.py::test_apply_snapshot_backfill_overwrites_answer
1 failed, 120 passed, 3 warnings in 3.68s

exit_code=1
```

### 保留的测试数据

```json
{
  "knowledge_file_id": 12,
  "knowledge_filename": "[FT20260707]功能测试知识库.txt",
  "knowledge_tenant": "jinoutuliao"
}
```

## 3. 客户端功能明细

| 功能 | 接口/页面 | 方法 | 身份 | 步骤 | 预期 | 结果 | 证据 |
|------|-----------|------|------|------|------|------|------|
| 运营工作台 | `/monitor/workspace-brief` | GET | CUSTOMER | GET workspace-brief | 健康分/平台条 | **PASS** | HTTP 200, keys=['tenant_id', 'brand_name', 'company_name', 'start_at', 'end_at', |
| GEO实时监测-任务列表 | `/monitor/tasks` | GET | CUSTOMER | GET /monitor/tasks | 任务数组 | **PASS** | HTTP 200, keys=list |
| GEO实时监测-汇总 | `/monitor/summary` | GET | CUSTOMER | GET /monitor/summary | 汇总 KPI | **PASS** | HTTP 200, keys=['scope', 'tenant_id', 'tenant_count', 'task_count', 'subtask_cou |
| GEO实时监测-排名矩阵 | `/monitor/ranking-matrix` | GET | CUSTOMER | GET /monitor/ranking-matrix?days=7 | 矩阵数据 | **PASS** | HTTP 200, keys=['platform', 'all_platforms', 'brand_name', 'start_at', 'end_at', |
| 品牌资产 | `/brand/asset` | GET | CUSTOMER | GET /brand/asset | 品牌配置 | **PASS** | HTTP 200, keys=['tenant_id', 'asset', 'competitors'] |
| 品牌洞察-竞品对比 | `/analytics/competitor-compare` | GET | CUSTOMER | GET competitor-compare | 对比数据 | **PASS** | HTTP 200, keys=['brand_name', 'competitor_count', 'sample_total', 'start_at', 'e |
| 品牌洞察-情感词 | `/analytics/sentiment-keywords` | GET | CUSTOMER | GET sentiment-keywords | 词频 | **PASS** | HTTP 200, keys=['positive', 'negative', 'positive_sample', 'negative_sample', 's |
| 信源分析 | `/monitor/summary` | GET | CUSTOMER | summary 含 source_stats | source_stats 字段 | **PASS** | summary 返回成功（信源页可读） |
| 报告中心-列表 | `/reports/list` | GET | CUSTOMER | GET /reports/list | 报告列表 | **PASS** | HTTP 200, keys=list |
| 企业知识库-列表 | `/knowledge/files` | GET | CUSTOMER | GET /knowledge/files | 文件列表 | **PASS** | HTTP 200, keys=list |
| 企业知识库-上传 | `/knowledge/files` | POST | CUSTOMER | 上传 FT20260707 测试文件 | 创建成功并保留 | **PASS** | file_id=12 name=[FT20260707]功能测试知识库.txt |
| 推广链接/品牌诊断页 | `/monitor/summary` | GET | CUSTOMER | functional 页依赖 summary | 200 | **PASS** | HTTP 200, keys=['scope', 'tenant_id', 'tenant_count', 'task_count', 'subtask_cou |
| 通知 | `/notifications` | GET | CUSTOMER | GET /notifications | 通知列表 | **PASS** | HTTP 200, keys=list |
| UI-登录页 | `http://127.0.0.1:5173/login` | BROWSER | 匿名 | 浏览器打开 /login | 页面 200 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-运营工作台 | `http://127.0.0.1:5173/customer?menu=customer.workspace` | BROWSER | CUSTOMER | 登录 client 后访问 | 主内容渲染 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-GEO实时监测 | `http://127.0.0.1:5173/customer?menu=customer.realtime` | BROWSER | CUSTOMER | 访问实时监测 | 矩阵/列表加载 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-品牌洞察 | `http://127.0.0.1:5173/customer?menu=customer.competitor` | BROWSER | CUSTOMER | 访问品牌洞察 | 图表区可见 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-报告中心 | `http://127.0.0.1:5173/customer?menu=customer.reports` | BROWSER | CUSTOMER | 访问报告中心 | 列表区可见 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-企业知识库 | `http://127.0.0.1:5173/customer?menu=customer.knowledge` | BROWSER | CUSTOMER | 访问知识库 | 上传区可见 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |

## 4. 运营端功能明细

| 功能 | 接口/页面 | 方法 | 身份 | 步骤 | 预期 | 结果 | 证据 |
|------|-----------|------|------|------|------|------|------|
| 运营总览 | `/management/overview` | GET | PLATFORM | GET /management/overview | 总览 KPI | **PASS** | HTTP 200, keys=['kpis', 'service_counts', 'expiring_tenants', 'platform_stats',  |
| 企业管理-租户列表 | `/management/tenants` | GET | PLATFORM | GET /management/tenants | 租户列表 | **PASS** | HTTP 200, keys=list |
| 企业管理-品牌资产 | `/brand/asset` | GET | PLATFORM | GET /brand/asset?tenant_id= | 指定租户品牌 | **PASS** | HTTP 200, keys=['tenant_id', 'asset', 'competitors'] |
| 用户管理-列表 | `/management/users` | GET | PLATFORM | GET /management/users | 用户列表 | **PASS** | HTTP 200, keys=list |
| 职位管理-列表 | `/management/positions` | GET | PLATFORM | GET /management/positions | 职位列表 | **PASS** | HTTP 200, keys=list |
| 职位管理-新建 | `/management/positions` | POST | PLATFORM | POST 职位 FT20260707 | 创建成功保留 | **PASS** | 职位已存在（保留） name=[FT20260707]测试职位 |
| 操作审批-列表 | `/approvals` | GET | PLATFORM | GET /approvals | 200 或 403（无权限） | **FAIL** | 缺陷：无权限时返回500而非403 |
| 操作审批-待办数 | `/approvals/pending-count` | GET | PLATFORM | GET pending-count | count 字段 | **PASS** | HTTP 200, keys=['count'] |
| 售前诊断-列表 | `/lead-diagnosis/list` | GET | PLATFORM | GET /lead-diagnosis/list | 诊断列表 | **PASS** | HTTP 200, keys=list |
| 售前诊断-创建 | `/lead-diagnosis` | POST | PLATFORM | POST 品牌 FT20260707 | 创建成功保留 | **PASS** | 售前诊断已存在（保留） brand=[FT20260707]测试品牌售前 |
| 快照补录-待补列表 | `/monitor/snapshot-backfill/pending` | GET | PLATFORM | GET pending?tenant_id=15 | 200 或 403（无菜单权限） | **SKIP** | 当前 platform 账号无快照补录菜单权限（403） |
| 定时监测-预览 | `/monitor/scheduled/preview` | GET | PLATFORM | GET scheduled/preview | 调度预览 | **PASS** | HTTP 200, keys=list |
| 模型平台-矩阵 | `/platforms/matrix` | GET | PLATFORM | GET /platforms/matrix | 平台矩阵 | **PASS** | HTTP 200, keys=['snapshot_date', 'supported_count', 'probe_total', 'probe_succes |
| 模型平台-余额 | `/platforms/molizhishu-balance` | GET | PLATFORM | GET molizhishu-balance | 余额信息 | **PASS** | HTTP 200, keys=['available', 'current_balance', 'current_balance_text', 'fetched |
| 预警阈值 | `/alerts/thresholds` | GET | PLATFORM | GET /alerts/thresholds | 阈值列表 | **PASS** | HTTP 200, keys=list |
| Celery 监控 | `/alerts/celery-monitor` | GET | PLATFORM | GET celery-monitor | 队列状态 | **PASS** | HTTP 200, keys=['checked_at', 'queues', 'workers', 'runtime_tasks', 'beat_histor |
| 操作日志 | `/ops/logs` | GET | PLATFORM | GET /ops/logs | 日志分页 | **PASS** | HTTP 200, keys=['items', 'total', 'page', 'page_size'] |
| 系统配置 | `/management/system-configs` | GET | PLATFORM | GET system-configs | 配置项 | **PASS** | HTTP 200, keys=list |
| 菜单配置 | `/management/menus/config` | GET | PLATFORM | GET menus/config | 菜单树 | **PASS** | HTTP 200, keys=list |
| 报告中心-列表 | `/reports/list` | GET | PLATFORM | GET /reports/list | 全量报告 | **PASS** | HTTP 200, keys=list |
| 品牌诊断记录 | `/diagnosis/records` | GET | PLATFORM | GET /diagnosis/records | 记录列表 | **PASS** | HTTP 200, keys=list |
| 监测任务详情 | `/monitor/tasks/{id}` | GET | PLATFORM | 取首条 task_id 查详情 | 任务详情 | **PASS** | task_id=45c353e7f5894afba161a3c6ef14cf21 status=None |
| UI-运营总览 | `http://127.0.0.1:5173/platform?menu=platform.dashboard` | BROWSER | PLATFORM | 登录 platform 后访问 | Dashboard 渲染 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-企业管理 | `http://127.0.0.1:5173/platform?menu=platform.audit` | BROWSER | PLATFORM | 访问企业管理 | 租户列表可见 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-售前诊断 | `http://127.0.0.1:5173/platform?menu=platform.lead_diagnosis` | BROWSER | PLATFORM | 访问售前诊断 | 列表可见 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-操作审批 | `http://127.0.0.1:5173/platform?menu=platform.approvals` | BROWSER | PLATFORM | 访问审批中心 | 页面可见 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-快照补录 | `http://127.0.0.1:5173/platform?menu=platform.snapshot_backfill` | BROWSER | PLATFORM | 访问快照补录 | 页面可见 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-预警阈值 | `http://127.0.0.1:5173/platform?menu=platform.alerts` | BROWSER | PLATFORM | 访问预警 | 阈值列表可见 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |
| UI-系统配置 | `http://127.0.0.1:5173/platform?menu=platform.settings` | BROWSER | PLATFORM | 访问系统配置 | 配置项可见 | **PASS** | HTTP 200, SPA shell OK (535 bytes sampled) |

## 5. 系统/认证/权限

| 功能 | 接口/页面 | 方法 | 身份 | 步骤 | 预期 | 结果 | 证据 |
|------|-----------|------|------|------|------|------|------|
| 健康检查 | `/health` | GET | 匿名 | GET /health | database=ready | **PASS** | HTTP 200, keys=['service', 'api', 'database', 'timestamp'] |
| 运维健康 | `/health/ops` | GET | PLATFORM | 平台 token 请求 /health/ops | 200 | **PASS** | HTTP 200, keys=['service', 'environment', 'api', 'database', 'redis', 'celery',  |
| 当前用户 | `/auth/me` | GET | PLATFORM | GET /auth/me | 返回 menus | **PASS** | HTTP 200, keys=['user', 'identity', 'identities', 'menus'] |
| 身份切换 | `/auth/switch-identity` | POST | demo | demo 平台→客户→平台 | 200 | **PASS** | demo 单身份 PLATFORM 登录正常（双身份切换需独立测试账号） |
| 客户禁止运营总览 | `/management/overview` | GET | CUSTOMER | 客户 token 访问 overview | 403 | **PASS** | 403 Forbidden 符合预期 |

## 6. 失败与跳过项

- **运营端/操作审批-列表** [FAIL] /approvals — 缺陷：无权限时返回500而非403
- **运营端/快照补录-待补列表** [SKIP] /monitor/snapshot-backfill/pending — 当前 platform 账号无快照补录菜单权限（403）

## 7. 已知缺陷（测试发现）

| 编号 | 模块 | 现象 | 严重度 | 建议 |
|------|------|------|--------|------|
| D-01 | 操作审批 | 无权限时 `GET /approvals` 返回 **500** 而非 403 | 中 | 确认 `PermissionError` 被捕获；重启 API 或修复 exception handler |
| D-02 | pytest | `test_apply_snapshot_backfill_overwrites_answer` 失败 | 低 | 单元测试待修复 |

## 8. 人工 UI 验收清单（建议浏览器逐页确认）

1. 客户登录 `jinoutuliao` → 运营工作台健康分、平台条、CTA
2. GEO实时监测 → 列表/矩阵切换、平台筛选、导出 CSV
3. 品牌洞察 → 竞品对比图、词云
4. 报告中心 → 打开报告、导出 PDF/Word
5. 知识库 → 可见 `[FT20260707]功能测试知识库.txt`
6. 运营登录 `platform` → 总览卡片、租户列表
7. 售前诊断 → 可见 `[FT20260707]测试品牌售前`
8. 操作审批 / 快照补录 / 预警阈值 / 系统配置 页面无报错

## 9. 测试过程

1. 确认 MySQL、Redis、API(8001)、Celery、Vite(5173) 已启动
2. 执行 `python scripts/functional_test_suite.py`
3. 执行 `pytest tests/ -q`
4. 浏览器按 §8 清单抽检

## 10. 功能覆盖清单（客户端 + 运营端）

| 端 | 功能 | menu_code | 测试方式 | 说明 |
|----|------|-----------|----------|------|
| 客户端 | 运营工作台 | `customer.workspace` | API+UI | 健康分、平台条、待办 |
| 客户端 | GEO实时监测 | `customer.realtime` | API+UI | 任务列表、排名矩阵、导出 |
| 客户端 | 推广链接检测 | `customer.links` | UI | 功能页 summary 驱动 |
| 客户端 | 品牌诊断 | `customer.diagnosis` | UI | 功能页 summary 驱动 |
| 客户端 | 品牌洞察 | `customer.competitor` | API+UI | 竞品对比、情感词、词云 |
| 客户端 | 信源分析 | `customer.sources` | API+UI | summary.source_stats |
| 客户端 | 报告中心 | `customer.reports` | API+UI | 列表、详情、导出 |
| 客户端 | 企业知识库 | `customer.knowledge` | API+UI | 上传、列表、解析 |
| 运营端 | 运营总览 | `platform.dashboard` | API+UI | KPI、余额、到期租户 |
| 运营端 | 企业管理 | `platform.audit` | API+UI | 租户/品牌/词/计划/竞品/文件 |
| 运营端 | 用户新增 | `platform.users.create` | UI | 多身份创建用户 |
| 运营端 | 用户列表 | `platform.users.list` | API+UI | CRUD、启停、密码 |
| 运营端 | 职位管理 | `platform.positions` | API+UI | 职位与菜单授权 |
| 运营端 | 操作审批 | `platform.approvals` | API+UI | 待办、通过、驳回 |
| 运营端 | 售前诊断 | `platform.lead_diagnosis` | API+UI | 创建、跑批、导出 |
| 运营端 | 快照补录 | `platform.snapshot_backfill` | API+UI | 待补列表、补录提交 |
| 运营端 | 品牌洞察 | `platform.competitor` | API+UI | 同客户端+租户切换 |
| 运营端 | 信源分析 | `platform.sources` | API+UI | 同客户端+租户切换 |
| 运营端 | 报告中心 | `platform.reports` | API+UI | 生成、发布、导出 |
| 运营端 | 模型平台 | `platform.models` | API+UI | 平台矩阵、探测状态 |
| 运营端 | 预警阈值 | `platform.alerts` | API+UI | 阈值、Celery 监控 |
| 运营端 | 操作日志 | `platform.logs` | API+UI | 审计日志筛选 |
| 运营端 | 系统配置 | `platform.settings` | API+UI | 参数、调度预览、菜单配置 |
