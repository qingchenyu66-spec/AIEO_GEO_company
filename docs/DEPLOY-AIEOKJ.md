# GEO Monitor 生产部署配置文档

> 目标环境：阿里云 ECS「GEO」+ 域名 `www.aieokj.com`  
> 文档日期：2026-07-09  
> 仓库：`https://github.com/livingFather/AIEO_GEO.git`  
> **本文不含真实密钥**；密钥只放服务器环境变量 / 密钥管理，勿提交 Git。  
>
> **部署进度（2026-07-09 14:05 CST）**  
> - 已完成：软件基线、代码同步、MySQL/Redis、迁移+seed、前端 build、systemd（api/beat/submit/sync/default）、Nginx:80  
> - 公网验收：`http://101.200.152.71/` → 200；`/api/v1/health` → `database: ready`  
> - 待你完成：DNS A 记录 → `101.200.152.71`；安全组确认 80/443；DNS 生效后执行 `certbot --nginx`  
> - 演示账号（seed）：`demo` / `platform` / `client`（密码见本地 seed 文档，生产请立即改密）

---

## 1. 资源清单（已确认）

| 项 | 值 |
|----|-----|
| 实例名 | GEO |
| 实例 ID | `i-2ze7whjqspvei5485hu7` |
| 地域 | 华北 2（北京）可用区 F |
| 规格 | `ecs.u2i-c1m4.2xlarge` · 8 vCPU / 32 GiB |
| 系统盘 | 40 GiB ESSD |
| 公网 IP | **`101.200.152.71`** |
| 私网 IP | `172.23.75.193` |
| 带宽 | 3 Mbps（固定） |
| 系统 | Ubuntu 24.04 64 位 |
| SSH 私钥（本机） | `C:\Users\Administrator\.ssh\geo-aieokj.pem`（备份副本：`D:\py代码\新建文件夹\GEO.pem`） |
| 正式域名 | `www.aieokj.com`（建议根域 `aieokj.com` 301 → www） |

---

## 2. 目标架构（推荐）

```text
用户浏览器
   │ HTTPS :443
   ▼
Nginx（本机）
   ├─ /          → 静态前端 dist（Vue build）
   └─ /api/      → 127.0.0.1:8001（uvicorn）
                      │
                      ├─ MySQL 8（本机或 RDS）
                      ├─ Redis 7（仅 127.0.0.1，强密码）
                      └─ Celery：beat + submit + sync + default
```

说明：

- **同域反代**：前端与 API 同属 `https://www.aieokj.com`，Cookie/CSRF 最简单。
- **不要**把 Redis `6379`、MySQL `3306`、Flower `5555`、uvicorn `8001` 暴露到公网安全组。
- Compose 当前缺 **default** 队列 worker，生产必须单独起 default（知识库解析 / 报告 / 诊断收尾）。

---

## 3. DNS 配置

在域名注册商 / 阿里云 DNS 控制台：

| 主机记录 | 类型 | 记录值 | TTL |
|----------|------|--------|-----|
| `www` | A | `101.200.152.71` | 600 |
| `@`（可选） | A | `101.200.152.71` | 600 |
| 或 `@` | CNAME | `www.aieokj.com` | 600（若注册商支持） |

验证（本机）：

```powershell
Resolve-DnsName www.aieokj.com
# 应看到 A 记录 = 101.200.152.71
```

**证书申请前必须 DNS 已生效**，否则 Let's Encrypt 会失败。

---

## 4. 安全组（阿里云控制台）

入方向建议：

| 端口 | 协议 | 授权对象 | 用途 |
|------|------|----------|------|
| 22 | TCP | **仅你的办公 IP**（勿 `0.0.0.0/0`） | SSH |
| 80 | TCP | `0.0.0.0/0` | HTTP（跳转 HTTPS / 证书校验） |
| 443 | TCP | `0.0.0.0/0` | HTTPS |

**不要开放**：3306、6379、8001、5555、5173。

---

## 5. SSH 登录

本机（PowerShell）：

```powershell
$pem = "$env:USERPROFILE\.ssh\geo-aieokj.pem"
# OpenSSH 要求私钥权限收紧
icacls $pem /inheritance:r
icacls $pem /grant:r "$env:USERNAME:(R)"

# Ubuntu 镜像常见用户为 root 或 ubuntu，以实际为准
ssh -i $pem -o StrictHostKeyChecking=accept-new root@101.200.152.71
# 或
ssh -i $pem ubuntu@101.200.152.71
```

私钥勿提交仓库、勿发聊天；丢失则在控制台重置密钥对。

---

## 6. 服务器软件基线

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl nginx mysql-server redis-server \
  python3.12-venv python3-pip build-essential \
  certbot python3-certbot-nginx

# Node 20 LTS（前端构建）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 可选：Docker（若用 compose 跑 Redis/Celery）
# sudo apt install -y docker.io docker-compose-v2
```

Redis 仅本机监听 + 密码（示例）：

```bash
sudo sed -i 's/^supervised no/supervised systemd/' /etc/redis/redis.conf
# 在 redis.conf 中设置：
# bind 127.0.0.1 ::1
# requirepass <强密码>
sudo systemctl enable --now redis-server
```

MySQL：创建库与用户（密码自行生成）：

```sql
CREATE DATABASE geo_monitor_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'geo_app'@'localhost' IDENTIFIED BY '<强密码>';
GRANT ALL PRIVILEGES ON geo_monitor_system.* TO 'geo_app'@'localhost';
FLUSH PRIVILEGES;
```

---

## 7. 代码与目录

```bash
sudo mkdir -p /opt/geo
sudo chown $USER:$USER /opt/geo
cd /opt/geo
git clone https://github.com/livingFather/AIEO_GEO.git
cd AIEO_GEO
```

建议目录约定：

| 路径 | 用途 |
|------|------|
| `/opt/geo/AIEO_GEO` | 代码 |
| `/opt/geo/AIEO_GEO/backend/.env` | 生产环境变量（权限 `600`） |
| `/opt/geo/AIEO_GEO/frontend/dist` | 前端构建产物 |
| `/var/log/geo/` | 应用日志（可选） |

---

## 8. 生产 `.env` 模板

复制 `backend/.env.example` → `backend/.env`，按下面改（**示例值请替换**）：

```env
APP_NAME=GEO Monitor API
APP_ENV=production
DEBUG=false
API_V1_PREFIX=/api/v1

# openssl rand -hex 32
SECRET_KEY=<至少32字节随机串>
ACCESS_TOKEN_EXPIRE_MINUTES=120
IDENTITY_TICKET_EXPIRE_MINUTES=30

DATABASE_HOST=127.0.0.1
DATABASE_PORT=3306
DATABASE_USER=geo_app
DATABASE_PASSWORD=<强密码>
DATABASE_NAME=geo_monitor_system
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=40

REDIS_ENABLED=true
REDIS_PASSWORD=<强密码>
REDIS_URL=redis://:<REDIS_PASSWORD>@127.0.0.1:6379/0
CELERY_ENABLED=true
CELERY_BROKER_URL=redis://:<REDIS_PASSWORD>@127.0.0.1:6379/1
CELERY_RESULT_BACKEND=redis://:<REDIS_PASSWORD>@127.0.0.1:6379/1

TRUSTED_HOSTS=www.aieokj.com,aieokj.com,101.200.152.71
CORS_ORIGINS=["https://www.aieokj.com","https://aieokj.com"]

AUTH_COOKIE_ENABLED=true
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
AUTH_CSRF_ENABLED=true
AUTH_EXPOSE_TOKEN_IN_BODY=false

FLOWER_ENABLED=false
# 若开启 Flower：FLOWER_BASIC_AUTH=admin:<强密码>，且仅内网访问

MOLIZHISHU_BASE_URL=https://business-api.molizhishu.com/api/business/monitor
MOLIZHISHU_TOKEN=<模力Token>
DEEPSEEK_API_KEY=<可选>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_REPORT_ENABLED=true
DEEPSEEK_KNOWLEDGE_PARSE_ENABLED=true
KNOWLEDGE_PARSE_TIMEOUT_MINUTES=10

SCHEDULE_TOLERANCE_MINUTES=60
MOLIZHISHU_SUBMIT_RATE_PER_MINUTE=30
MOLIZHISHU_SYNC_RATE_PER_MINUTE=60
```

```bash
chmod 600 /opt/geo/AIEO_GEO/backend/.env
```

---

## 9. 后端 / 前端构建与迁移

```bash
cd /opt/geo/AIEO_GEO/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=/opt/geo/AIEO_GEO/backend
alembic upgrade head
# 首次可按需：python -m scripts.seed_demo   # 生产慎用演示数据

# API（生产建议 systemd，见下节）
uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 2

cd /opt/geo/AIEO_GEO/frontend
npm ci
npm run build
# 产物：frontend/dist
```

Celery（四进程都要有）：

```bash
cd /opt/geo/AIEO_GEO/backend
source .venv/bin/activate
export PYTHONPATH=/opt/geo/AIEO_GEO/backend

celery -A app.celery_app beat --loglevel=info
celery -A app.celery_app worker -Q submit -n submit@%h -c 4 --loglevel=info
celery -A app.celery_app worker -Q sync -n sync@%h -c 4 --loglevel=info
celery -A app.celery_app worker -Q default -n default@%h -c 4 --loglevel=info
```

---

## 10. Nginx + HTTPS

仓库模板：

- 通用：`deploy/nginx/geo-monitor.conf`
- 本域名：`deploy/nginx/www.aieokj.com.conf`

安装：

```bash
sudo cp /opt/geo/AIEO_GEO/deploy/nginx/www.aieokj.com.conf \
  /etc/nginx/sites-available/www.aieokj.com.conf
sudo ln -sf /etc/nginx/sites-available/www.aieokj.com.conf \
  /etc/nginx/sites-enabled/www.aieokj.com.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# DNS 生效后申请证书
sudo certbot --nginx -d www.aieokj.com -d aieokj.com
```

证书续期：`certbot` 会装 timer；可用 `sudo certbot renew --dry-run` 自检。

---

## 11. systemd 单元（建议）

示例：`/etc/systemd/system/geo-api.service`

```ini
[Unit]
Description=GEO Monitor API
After=network.target mysql.service redis-server.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/geo/AIEO_GEO/backend
Environment=PYTHONPATH=/opt/geo/AIEO_GEO/backend
EnvironmentFile=/opt/geo/AIEO_GEO/backend/.env
ExecStart=/opt/geo/AIEO_GEO/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Celery beat / submit / sync / default 各写一个类似 unit（`ExecStart` 换成对应 celery 命令）。  
`User` 需对 `backend/storage` 有写权限。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now geo-api
# sudo systemctl enable --now geo-celery-beat geo-celery-submit geo-celery-sync geo-celery-default
```

---

## 12. 上线验收清单

- [ ] DNS：`www.aieokj.com` → `101.200.152.71`
- [ ] 安全组仅 22（限 IP）/80/443
- [ ] `https://www.aieokj.com` 证书有效，HTTP 301 → HTTPS
- [ ] `https://www.aieokj.com/api/v1/health` 返回 `database: ready`
- [ ] 登录 Cookie 带 `Secure`；跨域无 CORS 报错
- [ ] Celery beat + submit + sync + **default** 均在线
- [ ] Redis/MySQL 未对公网监听（`ss -lnt`）
- [ ] Flower 关闭或仅内网 + BASIC_AUTH
- [ ] `APP_ENV=production`、`DEBUG=false`、强 `SECRET_KEY`
- [ ] 模力 Token / DeepSeek Key 已配置且未进 Git

健康检查：

```bash
curl -sS https://www.aieokj.com/api/v1/health
curl -sS -o /dev/null -w "%{http_code}\n" https://www.aieokj.com/
```

---

## 13. 回滚与更新

### 13.1 日常更新（推荐）

生产机已接入 Git，Deploy Key 配置见 [`scripts/PROD-DEPLOY.md`](../scripts/PROD-DEPLOY.md)。

```bash
cd /opt/geo/AIEO_GEO
bash scripts/deploy_prod.sh
```

### 13.2 回滚到指定版本

```bash
cd /opt/geo/AIEO_GEO
git fetch origin
git checkout <tag或commit>
cd backend && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
cd ../frontend && npm ci && npm run build
sudo systemctl restart geo-api geo-celery-beat geo-celery-submit geo-celery-sync geo-celery-default
sudo systemctl reload nginx
```

### 13.3 无 Git 时的应急（不推荐）

从开发机 `scp` 变更文件 + 手动 `alembic upgrade` + `npm run build`，易漏文件；仅作临时热修。

---

## 14. 已知部署注意（来自 SECURITY / ADR）

| 风险 | 处理 |
|------|------|
| Compose 无 default worker | 生产用 systemd 显式起 default |
| 本机 8G 开发机易 OOM | 生产已是 32G，勿再把全家桶挤在开发机当生产 |
| 带宽 3 Mbps | 大报告/并发下载可能慢，必要时升带宽或 CDN |
| 系统盘 40G | 监测快照与知识库文件会涨，监控磁盘并挂数据盘 |

---

## 15. 相关文件

| 文件 | 说明 |
|------|------|
| `deploy/nginx/www.aieokj.com.conf` | 本域名 Nginx |
| `scripts/PROD-DEPLOY.md` | 生产机 git pull / Deploy Key |
| `scripts/deploy_prod.sh` | 一键更新脚本 |
| `backend/.env.example` | 环境变量说明 |
| `SECURITY.md` | 生产安全硬性要求 |
| `docs/ARCHITECTURE-ADR.md` | 架构决策与基线 |
