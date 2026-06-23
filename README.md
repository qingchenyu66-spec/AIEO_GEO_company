# GEO Monitor

AI 平台推广监测系统，采用前后端分离架构。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router
- 后端：Python、FastAPI、SQLAlchemy、Alembic
- 数据库：MySQL 8

## 本地启动

后端：

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd frontend
npm.cmd run dev
```

访问地址：

- 前端：http://127.0.0.1:5173
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/v1/health

## 演示账号

- 双身份账号：`demo` / `Geo@2026`
- 仅平台运营端：`platform` / `Admin@2026`
- 仅客户企业端：`client` / `Client@2026`

双身份账号登录后选择本次身份，也可以在页面右上角切换身份。

## 数据库迁移

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```
