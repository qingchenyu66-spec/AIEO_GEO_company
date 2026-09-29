# 生产机 Git 部署

服务器路径：`/opt/geo/AIEO_GEO`  
仓库：`git@github.com:livingFather/AIEO_GEO.git`

## 一次性：GitHub Deploy Key（必做）

服务器已生成只读密钥，需你在 GitHub 仓库添加 **Deploy key（只读）**：

1. 打开 [仓库 Settings → Deploy keys](https://github.com/livingFather/AIEO_GEO/settings/keys)
2. **Add deploy key**
3. Title：`geo-prod-101.200.152.71`
4. Key（复制整行）：

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICXwJSvSMvI8lNGoo8sJOGEFzGAHyey8x+2qPg/Mcyng geo-prod-deploy
```

5. 勾选 **Allow read access**（不要写权限）
6. 保存

验证（在服务器上）：

```bash
ssh -T git@github.com
# 应看到：Hi livingFather/AIEO_GEO! You've successfully authenticated...
cd /opt/geo/AIEO_GEO && git fetch origin main
```

## 日常更新

```bash
cd /opt/geo/AIEO_GEO
bash scripts/deploy_prod.sh
```

等价于：`git pull` → `alembic upgrade head` → `playwright install chromium` → `npm ci && npm run build` → 安装/重启 `geo-keyword-miner` → 重启 `geo-api` + reload nginx。

## GEO选词（keyword-miner）

生产走同域反代，不暴露公网端口：

- 服务：`geo-keyword-miner`（本机 `127.0.0.1:8088`）
- Nginx：`/keyword-miner/` → `8088`
- 历史列表：GEO MySQL `geo_keyword_miner_job`；选词服务本地 SQLite 作任务断点（`HISTORY_BACKEND=sqlite`）
- 密钥：`services/keyword-miner/.env` 的 `LLM_API_KEY`（首次可由 `backend/.env` 的 `DEEPSEEK_API_KEY` 自动填充）

单独安装/重启选词服务：

```bash
cd /opt/geo/AIEO_GEO
bash scripts/setup_keyword_miner.sh
curl -sS http://127.0.0.1:8088/api/health
curl -sS https://www.aieokj.com/keyword-miner/api/health
```

运营账号需 **重新登录** 才能看到侧栏「GEO选词」。

## 注意

单独检查 Chromium：

```bash
cd /opt/geo/AIEO_GEO
bash scripts/check_playwright.sh
```

运营健康检查 `GET /api/v1/health/ops` 含 `playwright_chromium`：`ready` 表示 PDF 导出可用。

## 首次接入（已完成 2026-07-10）

若新机器从零部署，在保留 `backend/.env` 的前提下：

```bash
cd /opt/geo/AIEO_GEO
bash scripts/bootstrap_prod_git.sh   # 需 Deploy Key 已配置
```

若 GitHub 暂不可达，可从开发机打 bundle 初始化：

```bash
# 开发机
git bundle create geo-deploy.bundle main
scp geo-deploy.bundle root@101.200.152.71:/tmp/

# 服务器
cd /opt/geo/AIEO_GEO
git init
git fetch /tmp/geo-deploy.bundle refs/heads/main:refs/heads/main
git checkout -f main
git remote add origin git@github.com:livingFather/AIEO_GEO.git
```

## 注意

- `backend/.env`、`backend/.venv`、`backend/storage/` 在 `.gitignore`，pull 不会覆盖
- 更新后运营账号需 **重新登录** 才能刷新菜单权限
- 不要 `git config` 改服务器全局用户信息（按项目规范）
