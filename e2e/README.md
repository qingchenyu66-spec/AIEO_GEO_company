# GEO Monitor RPA 测试

纯浏览器自动化，模拟人工：登录 → 点菜单 → 填表 → 提交。

## 前置

1. 后端 `http://127.0.0.1:8001`、前端 `http://127.0.0.1:5173` 已启动
2. Node.js 18+

## 首次安装

```powershell
cd e2e
copy .env.rpa.example .env.rpa   # 按需改账号
npm install
npm run install:browsers
```

## 运行

```powershell
cd e2e
npm test                 # 无头
npm run test:headed      # 有界面，便于观看 RPA 操作
```

或仓库根目录：

```powershell
.\scripts\run-rpa-tests.ps1
```

## 报告

- Markdown：`e2e/report/rpa-test-report.md`
- HTML：`e2e/report/html/index.html`
- 失败截图/录像：`e2e/test-results/`

## 覆盖

| 套件 | 说明 |
|------|------|
| `01-login` | 运营/客户登录 |
| `02-customer-journey` | 客户端 6 个菜单 + 实时监测切换 |
| `03-platform-journey` | 运营端 12 个菜单 |
| `04-snapshot-backfill-submit` | 快照补录填排名数字并提交（回归 trim bug） |
