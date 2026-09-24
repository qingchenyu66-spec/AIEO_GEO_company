# GEO 优化选词智能体 (MVP v2)

公司内部使用的关键词挖掘与拓词工具，对齐 Coze「GEO优化选词智能体」人设：
为不同行业企业客户提供 GEO 优化前期的**选词**与**拓词**，最终产出可直接给客户的 **Word(.docx) 交付报告**。

形态：**钉钉工作台网页应用**（一个 Web 应用挂到钉钉，团队在钉钉里点开即用，零安装）。

---

## 一、能力对照 Coze 人设

| Coze 人设要求 | 本工具实现 |
|---|---|
| 目标1 选词（问题/事实/长尾三类，结构化） | ✅ `选词` 任务，输出 关键词/类别/意图/评分/理由 |
| 目标2 拓词 50-100 条，覆盖 9 阶段全链路购买行为 | ✅ `拓词` 任务，覆盖 需求萌生→…→售后维保 |
| 拓词以自然问题短句呈现，锚定找服务商/采购场景 | ✅ 提示词强制约束，并禁止纯知识性提问 |
| 除品牌词外其他类别不含企业品牌名 | ✅ 提示词强制约束 |
| 每条标出目标 AI 平台热度值 | ✅ `预估热度`(0-100)，可按目标平台生成 |
| 技能：读取文件 / 读取网站 / 高阶词分析 | ✅ 支持官网 URL 抓取、上传 txt/md/csv/docx |
| 工作流：信息收集→选词→拓词 | ✅ 前端引导 + 后端串联 |
| 输出 Word(.docx) 且文件名不乱码 | ✅ `/api/export_docx` 生成，UTF-8 文件名 |
| 限制：按提供信息选词、不违反广告法 | ✅ 提示词约束，禁用绝对化用语 |

> **拓词铁律（已强化）**：每条拓词都必须是「找服务商 / 采购该服务」意图的**问题短句**，主语用品类词（如企业推广 / GEO优化），使 AI 回答必然落到服务商推荐与品牌植入（产品矩阵、门店布局、服务政策、品牌优势）。**严禁纯知识点/通用解释型提问**（如「都有哪些类型怎么选」「核心参数怎么看」「解决方案和产品的区别」）——这类词答案与品牌无关，已通过正负示例在提示词中硬性禁止；演示模板也已同步重写。
> **阶段说明**：`决策下单` 仅在产品/服务具有区域/门店属性时保留；纯线上服务可并入「同城渠道 / 下单履约」。

---

## 二、快速运行

```bash
cd keyword-miner

# 可选：配置大模型（不配置则进入演示模式）
export LLM_API_KEY="sk-xxxx"

# 需用装有 python-docx 的 venv 启动
../.venv/python envs/default/bin/python app.py
# 或：python3 app.py   （确保该 python 已 pip install python-docx）
# 打开 http://localhost:8080
```

未配置 `LLM_API_KEY` 时进入**演示模式**：用模板生成选词/拓词，界面、接口、Word 导出全部可用。
配置 Key 后由大模型真实挖掘，业务代码零改动。

---

## 三、大模型选型与切换

默认 **DeepSeek（deepseek-chat）**：中文强、价格极低、API 兼容 OpenAI 协议、易替换。
参数全走环境变量：

| 变量 | 默认 |
|---|---|
| `LLM_API_KEY` | 空（演示模式） |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | `deepseek-chat` |
| `LLM_TEMPERATURE` | `0.7` |

换模型只改这三个变量（通义/豆包/OpenAI 均 OpenAI 兼容），详见 v1 README 示例。

---

## 四、接入钉钉

### 4.1 钉钉工作台网页应用（前端，零安装）
钉钉开发者后台建「网页应用」，首页地址填本服务内网 URL（需公网/内网可达），
发布到工作台即可。团队在钉钉里点开即用。

### 4.2 钉钉群机器人（即时同步推送）
前端「推送到钉钉群」按钮：填群机器人 Webhook + 加签 secret，服务端 HMAC-SHA256 加签后推送 markdown 摘要。
零门槛，无需注册回调。

### 4.3 钉钉交互式聊天机器人（群里 @ 就出词）★第二阶段
在群里 @ 机器人，自动跑选词/拓词并回结果。

**创建与配置（钉钉开发者后台 → 应用开发 → 机器人）：**
1. 新建「企业内部机器人」，开启「接收消息」，消息接收模式选 **HTTP 回调**。
2. 消息接收地址填：`https://<你的域名>/api/dingtalk/callback`
   （本地联调用 ngrok/frp 等内网穿透暴露 8080 端口）。
3. 设置 **Token** 与 **EncodingAESKey**；机器人创建后复制其 **chatbotUserId**。
4. 把上述三项写入环境变量启动后端：

| 变量 | 说明 |
|---|---|
| `DINGTALK_TOKEN` | 机器人 Token |
| `DINGTALK_AES_KEY` | EncodingAESKey（43 位） |
| `DINGTALK_RECEIVE_ID` | 机器人 chatbotUserId（URL 验证必需） |
| `DINGTALK_DEFAULT_COMPANY` | 默认企业名（默认「艾迪亚控股集团」） |
| `DINGTALK_DEFAULT_PRODUCT` | 默认产品/服务（可选） |
| `PUBLIC_BASE_URL` | 公网地址（如 `https://geo.your-company.com`）。配置后 @ 出词回复里自动附带「完整 Word 报告」下载链接 |

```bash
export DINGTALK_TOKEN="xxx"
export DINGTALK_AES_KEY="43位EncodingAESKey"
export DINGTALK_RECEIVE_ID="chatbotUserId"
export PUBLIC_BASE_URL="https://geo.your-company.com"   # 可选：开启报告回链
/Users/aidiya/.workbuddy/binaries/python/envs/default/bin/python app.py
```

**一键启动**：项目根目录已提供 `start.sh`，自动定位 venv、停掉旧实例、导出示例环境变量（默认注释，按需打开），直接 `bash start.sh` 即可。

**@ 出词附带 Word 报告下载**：配置 `PUBLIC_BASE_URL` 后，机器人回复的 markdown 末尾会带一条 `📄 [完整 Word 报告](https://<域名>/api/report/<id>)` 链接；该链接指向本服务的内存报告接口 `/api/report/<id>`，点开即下载含全部选词/拓词的 `.docx`（UTF-8 文件名不乱码）。未配置 `PUBLIC_BASE_URL` 时回复不含链接，仅展示速览。

**工作机制：**
- 收到钉钉回调先做 **签名校验（SHA1）+ AES-256-CBC 解密**，校验失败返回 403。
- `type=urlverify` 的 URL 验证请求，解密后回送加密 echostr 完成验证。
- 文本消息：去掉 @ 提及后，用默认公司 + 用户文本作为资料，跑选词 + 9 阶段拓词（含合规校验），
  生成 markdown 回复。
- 若钉钉消息携带 `sessionWebhook`：先秒回「收到，正在生成…」确认，再由后台线程异步把结果推回会话（推荐，避免超时）；
  若无 `sessionWebhook`：同步加密返回结果（演示模式很快；接入大模型后建议走 sessionWebhook）。
- `/api/health` 返回 `dingtalk_callback: true` 表示回调已就绪。

> 本地联调可用 `python test_callback.py` 模拟钉钉签名回调，端到端验证加解密与出词。


---

## 五、接口说明

- `GET /api/health` → `{status, llm_configured, model}`
- `POST /api/mine`
  请求：`{company, product, materials, web_url, count, task("select"|"expand"|"both"), platforms[]}`
  返回：`{source, model, web_fetched, selection[], expansion{阶段:[{word,heat,note}]}}`
- `POST /api/ingest` → `{filename, data(base64)}` 返回 `{text}`（读取 txt/md/csv/docx）
- `POST /api/export_docx` → `{meta, selection, expansion, filename}` 返回 .docx 文件
- `GET /api/report/<id>` → 下载某次 @ 出词生成的 Word 报告（`id` 来自机器人回复里的下载链接；非法 id 返回 404）

---

## 六、合规校验（硬约束兜底）

即使大模型偶发越界，代码层也会兜底，确保交付物合规：
- **品牌名越界**：非「品牌对比」阶段的拓词若含企业品牌名 → 自动移除并报告（`word_policy.json` 的 brand_names + 企业名称 + 用户输入品牌词库）。
- **广告法风险**：含疑似绝对化违禁词（最/第一/国家级/唯一/顶级/全网最低…）→ 自动移除并报告。违禁词表在 `word_policy.json` 的 blacklist，可自行扩充。
- **去重**：选词与拓词跨结果重复 → 自动去重并报告。

响应中返回 `violations`（被移除项及原因）与 `dedup_removed`，前端会展示「合规校验」横幅。

### 6.1 拓词合规复核引擎（确定性规则 + 生成重写闭环）★

针对「拓词被大模型答成纯知识点」这一反复出现的返工点，新增两层防护（对应智能体训练功能 ①②）：

**（② 确定性复核规则引擎）** `review_word()` / `review_expansion()` 用正则 + 意图信号做可解释的硬判：
- **品牌名越界**：非「品牌对比」阶段的拓词含企业品牌名 → 判违规（与 6 节硬约束一致）。
- **强纯知识点**：命中 `核心参数 / 是什么意思 / 原理 / 定义 / 百科 / 基础知识 / 怎么理解 / 区别是什么 / 预算多少合适 / 费用多少合适` 等通用解释型问法 → 判违规（答案与品牌无关）。
- **弱列举/方法论**：命中 `有哪些类型 / 有什么区别 / 怎么选 / 怎么选型 / 怎么看 / 怎么区分` 等，且**完全缺失购买意图信号**（找 / 报价 / 多少钱 / 哪家靠谱 / 服务商 / 公司 / 比 …）→ 判违规。
  - 购买意图信号只保留「明确接洽服务商」的强信号，已剔除 `选 / 挑 / 方案 / 配置` 等会造成漏判的通用词，避免「GEO优化都有哪些服务模式怎么选」「方案怎么根据需求选型」这类被放过的返工词。

**（① 生成 → 复核 → 重写闭环）** `expand_mine()` 在 LLM 模式下：
1. 先生成拓词；2. 调 `review_expansion()` 全盘复核；3. 把**未达标的词 + 具体原因**作为反馈回写提示词，要求模型修正后重出全部拓词（保留已达标部分）；4. 最多 `max_rounds=2` 轮收敛，直到无违规或达上限。

> 验证：用此前被驳回的真实拓词（「都有哪些服务模式怎么选」「方案怎么根据需求选型」「品牌推广预算多少合适」「艾迪亚控股集团报价多少」）跑复核，全部命中拦截；合规词（「刚创业想做品牌推广该找哪类公司」「GEO优化大概多少钱怎么估算预算」）全部通过，漏判 0 / 误杀 0。
> 演示模式下 `_generate_expand()` 返回源为 `demo`，闭环不触发（演示模板本身已合规）；配置 `LLM_API_KEY` 后闭环自动生效。

**（④ 标准示例库，已接入）** 常量 `GOLDEN_EXAMPLES` 已基于用户提供的三份标准拓词方案（固万基紧固件 / 依波路手表 / Veloip 海外IP代理）提炼为 few-shot 样本，自动注入拓词提示词做口径对齐。三份样本的公共口径已固化为代码约束：
- **通用 9 阶段**：一律不带客户品牌名，全部锚定「找 XX 服务商 / 采购 XX」的高转化场景（例：`批量采购紧固件找哪家稳定`、`动态住宅IP代理服务商哪家稳定`）。
- **`品牌专属` 分组**（新增第 10 组）：带品牌名、直接关联企业产品/服务/政策/案例（例：`固万基支持非标定制吗`、`Veloip支持免费试用吗`）。品牌名**只许**出现在该分组，通用阶段出现即判违规并被重写；该分组的每条词也必须点名品牌。
- 演示模板 `EXPAND_DEMO` 已同步重写为采购锚定问法（原「都有哪些类型怎么选/方案怎么选型」等纯知识点问法已全部剔除）。

> 规则要点：通用阶段的「XXX 是什么」判为纯知识点（答案脱离品牌）；但**品牌专属**分组因问题已点名品牌，豁免该判定——这正对应示例中「固万基售后政策是什么」这类合规问法。

## 七、钉钉群推送

前端「推送到钉钉群」按钮：填入钉钉群机器人 Webhook（及加签 secret），
服务端用 HMAC-SHA256 加签后 POST markdown 摘要到群。`POST /api/push_dingtalk`
`{webhook, secret, company, selection, expansion}`。

> 注：交互式聊天机器人（在群里 @ 就出词）需注册钉钉「机器人」应用并配置消息回调，
> 属第二阶段；群机器人推送是零门槛的即时同步方案。

## 八、热度数据（可插拔）

拓词热度目前为模型预估（无真实数据源）。`enrich_heat(words, platforms)` 为预留钩子：
接入某 AI 平台搜索指数 API 后，返回 `{word: heat}` 即可自动覆盖模型预估，无需改其他代码。

## 九、目录结构

```
keyword-miner/
├── app.py                # 后端 v3：选词/拓词提示词 + 网站抓取 + 文件读取 + 合规校验 + 钉钉群推送 + 钉钉交互回调 + 报告下载 + Word 生成
├── dingtalk_crypto.py    # 钉钉回调加解密（SHA1 签名 + AES-256-CBC）
├── start.sh              # 一键启动脚本（定位 venv + 停旧实例 + 导出环境变量）
├── test_callback.py      # 本地模拟钉钉签名回调的端到端测试
├── test_report.py        # 验证 @ 出词报告回链 + /api/report 下载的端到端测试
├── web/index.html        # 单页前端（即钉钉工作台网页应用）
├── word_policy.json      # 品牌词库 + 广告法违禁词黑名单（可编辑）
├── README.md
└── 示例_GEO选词建议_*.docx   # 演示模式产出的示例交付文件
```

> 注意：热度值为模型基于语义的**预估**，非真实平台后台数据；如需真实流量，可后续接入各 AI 平台搜索指数数据源。
