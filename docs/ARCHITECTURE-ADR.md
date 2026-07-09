# GEO Monitor · 架构决策记录 / 量化指标基线 / 技术风险清单

> 版本：2026-07-09  
> 来源：仓库代码与配置（`README.md`、`backend/app/celery_app.py`、`backend/.env.example`、`backend/docker-compose.yml`、`backend/scripts/*`）及当日开发机故障观测。  
> **边界**：指标多为配置默认值与一次本机观测，**不是**线上 SLO。

---

## 1. 架构决策记录 (ADR)

| ID | 决策 | 状态 | 选择 | 为何 | 后果 |
|----|------|------|------|------|------|
| ADR-001 | 前后端分离 + 同域 `/api` 代理 | Accepted | Vue SPA(5173) → Vite 代理 → FastAPI(8001)；生产拟 Nginx 同域反代 | 热更新与 API 解耦；同源简化 Cookie/CSRF | 端口/代理错配即 502；生产必须改 CORS/TrustedHost |
| ADR-002 | Celery 三队列 + Beat | Accepted | `submit` / `sync` / `default`；Beat 驱动到点提交与轮询同步 | 提交与回拉速率不同；隔离模力限流 | 缺任一 worker 则对应链路静默停；Windows `solo` 并发名不副实 |
| ADR-003 | JWT Cookie + CSRF 双提交 | Accepted | HttpOnly Cookie；写操作 `X-CSRF-Token`；Bearer 可豁免 CSRF | 浏览器会话安全；脚本仍可用 Bearer | 生产 `AUTH_COOKIE_SECURE=true`；跨域需 SameSite |
| ADR-004 | 多租户双身份 | Accepted | `PLATFORM` / `CUSTOMER`；菜单权限挂身份/岗位 | 运营与客户同系统、权限面不同 | 定时任务用首个 PLATFORM 身份；无平台账号则调度失败 |
| ADR-005 | 模力轮询同步（暂无回调） | Accepted (interim) | 提交后 Celery sync 轮询；`CALLBACK_URL` 预留 | 对接成本低、可控重试 | 规模上升时 sync 成本线性增长（见 BACKLOG） |
| ADR-006 | SQLAlchemy 2 + Alembic + MySQL 8 | Accepted | ORM + 迁移；PyMySQL；池 20+40 | 事务与权限模型清晰 | 50–100 租户未压测 |
| ADR-007 | Windows 开发 solo / Linux 生产 prefork | Accepted (dev ceiling) | 本机 `--pool=solo`；Compose/生产多 worker | Windows 无可靠 prefork | `-c N` 在 Windows 不代表真并行；开发机易内存打满 |
| ADR-008 | 正式域名 `www.aieokj.com` | Proposed | 公网入口拟用该域名 | 品牌上线 | DNS 尚未解析；需 HTTPS/CORS/Cookie 一并切换 |

### Beat 调度基线（Asia/Shanghai）

| 任务 | 队列 | 频率 |
|------|------|------|
| `scan_due_schedules` | submit | `*/5`，09–20 |
| `scan_pending_syncs` | sync | 每分钟 |
| `check_queue_backlog` | sync | `*/5` |
| `scan_due_lead_diagnosis` | default* | `*/5`，09–21 |
| `finalize_lead_diagnoses` | default | `*/10`，09–22 |
| `scan_due_scheduled_reports` | default | 每日 20:00 |

\* `scan_due_lead_diagnosis` 未在 `task_routes` 显式路由，落入 default。

---

## 2. 量化指标基线

| 指标 | 基线值 | 单位 | 来源 |
|------|--------|------|------|
| API 端口 (dev / compose) | 8001 / 8000 | port | `start_api.ps1` / `docker-compose` |
| 前端端口 | 5173 | port | `vite.config.ts` |
| Access token TTL (dev 默认) | 480 | min | `.env.example` |
| Access token TTL (prod 建议) | 120 | min | `.env.example` 注释 |
| Identity ticket TTL | 30 | min | `.env.example` |
| Schedule 容差 | ±60 | min | `SCHEDULE_TOLERANCE_MINUTES` |
| 模力提交 / 同步速率上限 | 30 / 60 | /min | `MOLIZHISHU_*_RATE_PER_MINUTE` |
| 模力限流最大等待 | 120 | s | `.env.example` |
| 单次扫描最大 prompts | 50 | count | `CELERY_SCAN_SUBMIT_MAX_PROMPTS` |
| 同步批大小 | 500 | tasks | `CELERY_SYNC_BATCH_LIMIT` |
| 终态宽限 | 24 | h | `CELERY_SYNC_TERMINAL_GRACE_HOURS` |
| submit 队列告警 | 50 / 150 | warn/crit | `.env.example` |
| sync 队列告警 | 100 / 300 | warn/crit | `.env.example` |
| DB pool / overflow | 20 / 40 | conn | `.env.example` |
| Win submit/sync/default `-c` | 4 / 8 / 2 | solo | `start_celery.ps1` |
| Compose 容量假设 | 50 租户×4 组 ≈200 submit @30/min ≈7 | min | `docker-compose` 注释 |
| 功能测试 (2026-07-07) | 51/53 | pass | `docs/functional-test-report-FT20260707.md` |
| pytest (同日) | 120/121 | pass | 同上 |
| 本机物理内存 (观测) | ~8GB，占用 ≈92–96% | GB | 2026-07-09 故障排查 |
| Alembic 迁移数 | ~46 | files | `backend/migrations/versions/` |

**说明**：`CELERY_SUBMIT_RATE_LIMIT` / `CELERY_SYNC_RATE_LIMIT` 在配置中存在，但代码未引用；实际限流走模力 `rate_limiter`。

---

## 3. 技术风险清单

| ID | 级别 | 域 | 风险 | 证据 | 影响 | 缓解 |
|----|------|-----|------|------|------|------|
| R1 | Critical | Runtime | 开发机内存打满导致 uvicorn/Vite 无声退出 | 8GB 空闲~0.2GB；8001 Connection refused | 登录 502/白屏；Celery 仍跑 | 升内存或拆机；API 保活+落盘日志 |
| R2 | High | Deploy | Compose 未定义 default 队列 worker | `docker-compose` 仅 submit/sync | 知识库/报告/诊断收尾可能不跑 | 补 default worker 或改路由 |
| R3 | High | Deploy | 生产域名/CORS/Cookie 未切换 | CORS 仅 localhost；`aieokj.com` NXDOMAIN | 上线后跨域或 Cookie 失败 | DNS+HTTPS+配置清单化发布 |
| R4 | High | Ops | API 无进程守护，Celery 有计划任务 | 手动 `start_api.ps1` vs schtasks | API 挂而 Beat 仍投递 | API 与 Celery 同级保活 |
| R5 | Medium | Windows | uvicorn `--reload` 僵尸占用 8001 | `start_api.ps1` 清理逻辑 | 旧路由/多实例混乱 | 生产关 reload；强杀端口 |
| R6 | Medium | Windows | Celery solo + inspect 不可靠 | `celery_queue_monitor` 注释 | 误报离线；吞吐预期虚高 | Linux prefork；用队列深度监控 |
| R7 | Medium | Integration | 模力无回调，纯轮询 | BACKLOG；`CALLBACK_URL` 空 | 规模上升 sync 成本升 | 落地 webhook；拆分提交批 |
| R8 | Medium | Scale | 50–100 租户未压测 | `docs/BACKLOG.md` | 队列/MySQL 天花板未知 | 按 Compose 假设做负载测试 |
| R9 | Low | Config | `CELERY_*_RATE_LIMIT` 未接线 | config 有键、代码无引用 | 运维误调无效参数 | 删除或真正接入 |
| R10 | Low | Security | Flower 无 BASIC_AUTH | `security_baseline` | 暴露队列元数据 | 生产强制 auth |

---

## 4. 建议的下一决策点

1. 确认 `www.aieokj.com` 部署拓扑（同域反代 vs `api` 子域）→ 关闭 **ADR-008**。  
2. Compose 补 **default** worker → 关闭 **R2**。  
3. 开发机升内存或给 API 保活+落盘日志 → 关闭 **R1/R4**。
