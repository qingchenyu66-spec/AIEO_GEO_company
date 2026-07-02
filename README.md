# GEO Monitor

AI 大模型品牌监测与 GEO 优化平台。支持多租户、双端身份（平台运营 / 客户企业），对接模力指数完成定时监测，并提供排名矩阵、舆情分析、信源追踪等能力。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、ECharts、Lucide |
| 后端 | Python 3.11+、FastAPI、SQLAlchemy 2、Alembic、Pydantic Settings |
| 数据库 | MySQL 8 |
| 外部服务 | 模力指数（Molizhishu）监测 API |

## 项目结构

```
GEO优化/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/          # REST 接口
│   │   ├── models/          # ORM 模型
│   │   ├── services/        # 业务逻辑（监测、调度、品牌、权限等）
│   │   └── schemas/         # 请求/响应模型
│   ├── migrations/          # Alembic 数据库迁移
│   └── scripts/             # 种子数据、定时任务脚本
├── frontend/                # Vue 3 前端
│   └── src/
│       ├── views/portal/    # 门户页面与 composables
│       ├── services/        # API 客户端
│       └── composables/     # 通用组合式函数（图表懒加载等）
└── README.md
```

## 环境要求

- Node.js 18+
- Python 3.11+
- MySQL 8（库名默认 `geo_monitor_system`）

## 首次部署

### 1. 数据库

创建 MySQL 库与用户，例如：

```sql
CREATE DATABASE geo_monitor_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'geo_app'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON geo_monitor_system.* TO 'geo_app'@'%';
FLUSH PRIVILEGES;
```

### 2. 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt

# 复制并编辑环境变量
copy .env.example .env
# 必填：SECRET_KEY、DATABASE_*；监测任务需配置 MOLIZHISHU_TOKEN

.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.seed_demo
```

`.env` 常用项（完整示例见 `backend/.env.example`）：

```env
SECRET_KEY=your-long-random-secret
DATABASE_HOST=127.0.0.1
DATABASE_PORT=3306
DATABASE_USER=geo_app
DATABASE_PASSWORD=your-password
DATABASE_NAME=geo_monitor_system
CORS_ORIGINS=["http://127.0.0.1:5173","http://localhost:5173"]
MOLIZHISHU_TOKEN=your-molizhishu-token
```

### 3. 前端

```powershell
cd frontend
npm install
npm run dev
```

## 日常开发启动

**后端**（项目根目录下）：

```powershell
cd backend
$env:PYTHONPATH="d:\py代码\GEO优化\backend"   # 按实际路径调整
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

**前端**：

```powershell
cd frontend
npm run dev
```

访问地址：

| 服务 | 地址 |
|------|------|
| 前端 | http://127.0.0.1:5173 |
| API 文档 | http://127.0.0.1:8001/docs |
| 健康检查 | http://127.0.0.1:8001/api/v1/health |

前端通过 Vite 代理将 `/api` 转发到 `http://127.0.0.1:8001`。

## 演示账号

执行 `seed_demo` 后可用（演示企业：北京艾亿欧 / 艾迪亚）：

| 账号 | 密码 | 说明 |
|------|------|------|
| `demo` | `Geo@2026` | 双身份：登录后可切平台运营 / 客户企业 |
| `platform` | `Admin@2026` | 仅平台运营端 |
| `client` | `Client@2026` | 仅客户企业端 |

登录后可在右上角切换身份。客户侧为只读查看监测结果，定时任务由平台端配置与触发。

## 功能概览

### 平台运营端

- 运营总览、企业管理（品牌资产 / 监测词组 / 竞品 / 调度计划）
- 用户与权限、菜单配置、操作日志、系统配置
- 触发定时监测、预览调度问题列表

### 客户企业端

- **运营工作台**：监测 KPI、趋势、信源概览
- **实时检测**：按调度轮次查看检测结果；排名矩阵（推荐类问题）；子任务详情与快照
- **舆情监控**：口碑类问题情感分布、负面明细、平台对比、CSV 导出
- **信源分析 / 品牌诊断 / 竞品分析 / 报告中心 / 企业知识库**

## 监测与调度说明

- 监测任务提交与结果同步依赖 **模力指数 API**（`MOLIZHISHU_TOKEN`）。
- 平台端在「企业管理」中配置监测词组、AI 平台、定时计划；到点由脚本或手动触发。
- 定时执行脚本（Windows）：

```powershell
cd backend\scripts
.\run_due_scheduled_tasks.cmd      # 提交到期调度任务
.\sync_pending_monitor_tasks.cmd   # 同步进行中任务结果
```

- 问题生成采用 **词组级去重（B+）**：行业词组 2 问、品牌词组基础问 + 口碑 + 竞品对比，避免重复子任务膨胀。
- **排名类**与**口碑/介绍类**问题分开统计：实时检测看排名，舆情页只看口碑类情感。

## 数据库迁移

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

新建迁移：

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe change"
```

## 构建

```powershell
cd frontend
npm run build
```

产物输出至 `frontend/dist/`，需由 Web 服务器托管并与后端 API 同域或配置反向代理。

## 常见问题

**登录 502 / 网络错误**  
确认后端已在 `8001` 端口运行，且 `/api/v1/health` 返回 `database: ready`。

**监测无数据**  
检查 `MOLIZHISHU_TOKEN`、企业品牌资产是否已审核配置、是否已执行调度脚本或手动触发监测。

**迁移冲突**  
若存在多个 head，执行 `alembic merge` 生成合并迁移后再 `upgrade head`（仓库内已有 merge 示例迁移）。

## License

内部项目，未经授权请勿对外分发。
