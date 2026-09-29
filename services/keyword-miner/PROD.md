# GEO 选词服务（生产）

代码目录：`services/keyword-miner/`

## 生产形态

| 项 | 值 |
|---|---|
| systemd | `geo-keyword-miner` |
| 监听 | `127.0.0.1:8088` |
| 反代 | `https://www.aieokj.com/keyword-miner/` |
| 历史列表 | GEO MySQL 表 `geo_keyword_miner_job` |
| 任务断点 | 选词服务本地 SQLite（`HISTORY_BACKEND=sqlite`，重启可续读 done / 中断标 error） |
| 密钥 | `services/keyword-miner/.env` |

门户页默认用同域 `/keyword-miner`，无需再配 `VITE_KEYWORD_MINER_ORIGIN`。
iframe 用 Cookie + CSRF 把任务同步到 `/api/v1/keyword-miner/jobs`。

## 首次上线检查

1. 代码已合入 `main` 并 `bash scripts/deploy_prod.sh`
2. `systemctl is-active geo-keyword-miner`
3. `curl -sS http://127.0.0.1:8088/api/health` 返回 `llm_configured: true`
4. 浏览器打开运营台 → GEO选词，iframe 可加载
5. 平台账号重新登录后侧栏可见菜单

## 本地开发

```bash
cd services/keyword-miner
# 或继续用 _tmp 副本；默认 http://127.0.0.1:8080
export LLM_API_KEY=...
python app.py
```
