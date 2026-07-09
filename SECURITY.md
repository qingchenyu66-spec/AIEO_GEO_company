# GEO 优化系统安全策略与剩余风险

更新时间：2026-07-09  
范围：`D:\py代码\GEO优化`，FastAPI + SQLAlchemy + MySQL + Redis + Celery + Vue3/Vite。  
说明：本文记录当前安全基线、生产约束和已接受的剩余风险，不声明系统绝对无漏洞。

## 生产硬性要求

| 项目 | 要求 |
| --- | --- |
| 密钥 | `SECRET_KEY`、数据库密码、`MOLIZHISHU_TOKEN`、`DEEPSEEK_API_KEY`、`REDIS_PASSWORD` 必须来自环境变量或密钥管理服务 |
| Redis | 必须配置 `REDIS_PASSWORD`；Docker Compose 默认不再把 6379 暴露到宿主机 |
| CORS | `CORS_ORIGINS` 只能配置真实域名，不允许生产环境使用 `*` + 凭证 |
| Cookie | HTTPS 后必须设置 `AUTH_COOKIE_SECURE=true` |
| Flower | 生产环境必须设置 `FLOWER_BASIC_AUTH=user:password` |
| Debug | 生产环境必须 `APP_ENV=production`、`DEBUG=false` |
| 知识库解析 | 必须运行默认 Celery Worker；Beat 会定时处理超时解析任务 |
| 日志 | 不允许把 Token、密码、API Key、完整请求头写入业务日志 |

## 本轮已关闭的高危/严重风险

| ID | 类别 | 处理结果 |
| --- | --- | --- |
| H1 | CWE-798 / A02 密钥泄露风险 | `.gitignore` 增补本地 env；示例配置只保留占位符 |
| H2 | CWE-1188 / A05 Redis 弱配置 | Compose 强制 `REDIS_PASSWORD`，取消宿主机端口发布 |
| H3 | CWE-863 / A01 销售范围越权 | 销售身份只认 `PLATFORM_SALES` 稳定编码，不再按中文职位名判断 |
| H4 | CWE-400 同步饥饿 | 待同步任务按最旧优先处理，避免旧任务长期卡住 |
| H5 | CWE-327 弱哈希 | MD5 改为 SHA-256，用于编码/颜色等非密码场景 |
| H6 | A06 依赖漏洞 | 升级高危依赖，移除 `python-jose`/`ecdsa` 链路，改用 `PyJWT` |

## 已记录剩余 Medium / 待办

| ID | 风险 | 缓解措施 | 计划 |
| --- | --- | --- | --- |
| M1 | Alembic 历史迁移脚本存在 Bandit B608 固定 SQL 提示 | 仅内部迁移执行，当前 SQL 不拼接外部输入；生产迁移需由运维执行并留痕 | 后续迁移改成参数化 `sa.text(...).bindparams(...)` |
| M2 | 内部脚本使用 `urlopen` 被 Bandit B310 提示 | 脚本不暴露为线上 API；只允许内网/人工运行 | 后续统一封装 URL allowlist |
| M3 | 职位菜单同步可能覆盖自定义授权 | 本轮未改 schema，已在报告登记 | v0.3 增加 `grant_source=position/custom` |
| M4 | 本机 `backend/.env` 含真实密钥 | 已 gitignore；如曾外发或截图需要轮换 | 运维上线前统一换密 |
| M5 | ECharts chunk 较大 | 已分包但 vendor 仍偏大；不影响安全基线 | 性能迭代继续拆图表按需加载 |

## 复验命令

```powershell
cd D:\py代码\GEO优化\backend
python -m pip_audit -r requirements.txt
python -m bandit -r app scripts migrations -x .venv,storage -ll
python -m compileall app tests
pytest -q --tb=short

cd D:\py代码\GEO优化\frontend
npm audit --audit-level=high --omit=dev
npm run build
```

## 当前复验摘要

| 检查项 | 结果 |
| --- | --- |
| Python 依赖 Critical/High | 0，`pip-audit` 未发现已知漏洞 |
| Node high/critical | 0，`npm audit --audit-level=high --omit=dev` 通过 |
| Bandit High | 0 |
| 后端测试 | 157 passed，1 个第三方弃用警告 |
| 前端构建 | 通过，剩余 chunk 体积与 CSS `:deep` 样式警告 |

