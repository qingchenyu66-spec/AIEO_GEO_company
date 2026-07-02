# 待办列表

## 监测 / 舆情

- **调度增加口碑类问题**：在定时提交监测任务时，除排名监测词外，额外生成并提交口碑/介绍类 prompt（如「{品牌}口碑评价怎么样」「{品牌}是做什么的」等），使舆情监控有独立口径的样本，与排名类问题分开统计。



## 数据库压力

- 当数据量级到50甚至100家, 每家监控词达到10左右测试MySQL数据库



## 并发冲击模力

- 当量级过大且未错峰运行,模力API可接受最大并发数测试



## 测试上线前 — 模力提交与 Callback（暂缓，上线前处理）

> 背景：大批量「10 prompts × 10 platforms = 100 子任务 / 1 主任务」易在模力侧出现部分平台长期 `pending`；Callback 可加速结果入库。约束：**监测平台数量不能减少**（企业购买的全部平台仍须覆盖）。

### 拆分提交（推荐方案 A：按平台拆分）

- [ ] 新增配置：`MOLIZHISHU_SUBMIT_SPLIT_MODE=platform|none`、`MOLIZHISHU_SUBMIT_PLATFORMS_PER_BATCH=1`（高峰可改 2～3 折中 API 次数）
- [ ] 实现 `split_submit_payloads()`：每次 submit 带**全部 prompts**，按平台分组（默认 1 平台/次）；**不减少平台数**
- [ ] `submit_schedule_group` 改为 batch 提交；同一调度窗口共享 `batch_id`
- [ ] DB 迁移：`geo_monitor_task.batch_id`；`geo_monitor_schedule_run` 支持多 `task_id`（如 `task_ids_json`）及 `partial` 状态
- [ ] 部分 platform batch 失败：Celery 重试失败分片 + 告警（避免整窗误判为成功）
- [ ] 更新 `preview_scheduled_tasks`：展示「将提交 N 次 API，覆盖 M 个平台」
- [ ] 前端：同一 `schedule_window_key` / `batch_id` 聚合为「一次监测」进度

**不建议默认 1 prompt × 1 platform（100 次/词组）**：50 企业高峰 API 量过大，易超出调度窗口与 `MOLIZHISHU_SUBMIT_RATE_PER_MINUTE`。

### Callback 回调

- [ ] 配置公网 HTTPS：`MOLIZHISHU_CALLBACK_URL=https://<域名>/api/v1/monitor/molizhishu/callback?token=...`（本机 127.0.0.1 无效）
- [ ] 新增 `POST /api/v1/monitor/molizhishu/callback`：无 JWT，query token 鉴权；复用 `_upsert_subtask` + `GeoMonitorCallbackEvent` 幂等（`payload_hash`）
- [ ] 提交时继续带 `callbackUrl`（已有 `_build_submit_payload` 逻辑）
- [ ] 保留 Celery `scan_pending_syncs` 1 分钟兜底 sync

### 上线前需确认

- [ ] Callback 公网入口（域名 / Nginx / 云主机或穿透）
- [ ] 50 企业同时到点时 `platforms_per_batch` 取值（1 vs 2～3）
- [ ] 与模力确认 Callback  payload 格式与重试策略（文档「Callback 回调」章节）

**涉及文件（预估）**：`monitor_service.py`、`schedule_service.py`、`monitor.py`（endpoint）、`models/monitor.py`、Alembic 迁移、`.env.example`、前端实时监测列表。

