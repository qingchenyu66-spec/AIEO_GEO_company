#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GEO 优化选词智能体 · 后端 API 服务 (MVP v3)
============================================
能力：选词（问题/事实/长尾三类） + 拓词（用户购买全链路 9 阶段，含 AI 平台预估热度）
输入：企业名称 / 产品服务 / 官网 URL（服务端抓取）/ 资料文本或文件
交付：结构化结果 + 可直接下载的 Word(.docx) 报告
大模型：默认 DeepSeek（OpenAI 兼容），环境变量可切换；无 Key 时进入演示模式。

依赖：python-docx（用于生成 .docx）。其余为标准库。
运行：python3 app.py  （建议用装有 python-docx 的 venv）
"""
import os
import io
import re
import json
import base64
import hashlib
import hmac
import time
import datetime
import threading
import secrets
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

try:
    from dingtalk_crypto import DingTalkCrypto
except Exception:  # noqa: BLE001 - 无 pycryptodome 时仍可跑选词/导出
    DingTalkCrypto = None  # type: ignore[misc, assignment]

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

# ---------- 大模型配置（OpenAI 兼容）----------
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))

# ---------- 钉钉交互式机器人（消息回调）配置 ----------
# 在「钉钉开发者后台 → 应用开发 → 机器人」创建企业内部机器人，
# 开启「接收消息（HTTP 回调）」，把本服务的 /api/dingtalk/callback 填为消息接收地址，
# 并填入下方的 Token / EncodingAESKey；chatbotUserId 填到 DINGTALK_RECEIVE_ID。
DINGTALK_TOKEN = os.getenv("DINGTALK_TOKEN", "")
DINGTALK_AES_KEY = os.getenv("DINGTALK_AES_KEY", "")
DINGTALK_RECEIVE_ID = os.getenv("DINGTALK_RECEIVE_ID", "")  # 机器人 chatbotUserId
DINGTALK_DEFAULT_COMPANY = os.getenv("DINGTALK_DEFAULT_COMPANY", "艾迪亚控股集团")
DINGTALK_DEFAULT_PRODUCT = os.getenv("DINGTALK_DEFAULT_PRODUCT", "")
# 公网基础地址：配置了之后，@ 出词回复里会附带「完整 Word 报告」下载链接（指向本服务的 /api/report/<id>）。
# 例如：https://geo.your-company.com
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_INDEX = os.path.join(HERE, "web", "index.html")

STAGES = [
    "需求萌生", "品类筛选", "品牌对比", "产品选型", "价格预算",
    "同城渠道", "决策下单", "下单履约", "售后维保",
]
# 品牌专属：专门的「带品牌名」分组（对齐标准示例的「品牌专属类」）。
# 9 个通用阶段一律不带客户品牌名；品牌名只许出现在本分组，由本分组直接关联企业。
BRAND_STAGE = "品牌专属"
# 全部输出分组（通用 9 阶段 + 品牌专属）。
# 需要遍历「所有分组」的地方用 ALL_STAGES；需要区分渲染「品牌专属」的地方用 STAGES + BRAND_STAGE。
ALL_STAGES = STAGES + [BRAND_STAGE]

# ---------- 合规词库（品牌词库 / 广告法黑名单）与校验 ----------
POLICY_PATH = os.path.join(HERE, "word_policy.json")
def load_policy():
    try:
        with open(POLICY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"brand_names": [], "blacklist": []}
POLICY = load_policy()
DEFAULT_BLACKLIST = [
    "国家级", "唯一", "顶级", "极致", "绝无仅有", "史无前例", "万能", "百分百",
    "销量第一", "全网最低", "领导品牌", "领先品牌", "永久", "首选", "最佳", "极品",
    "至尊", "终极", "完美", "NO.1", "No.1", "no.1", "王牌", "最高级", "第一品牌",
    "销量冠军", "独家", "唯一指定",
]


def _norm(w):
    return re.sub(r"\s+", "", str(w))


def validate_and_filter(selection, expansion, brand_terms, blacklist):
    """执行：品牌名越界检测、广告法疑似违禁词检测、跨结果去重。
    返回 (selection, expansion, violations, dedup_removed)。"""
    brands = [b.strip() for b in (brand_terms or []) if b.strip()]
    bl = list(blacklist or [])
    violations, dedup_removed, seen = [], [], set()

    sel_out = []
    for k in selection:
        w = k.get("word", "")
        nw = _norm(w)
        if nw and nw in seen:
            dedup_removed.append({"word": w, "where": "选词"})
            continue
        if nw:
            seen.add(nw)
        hit = next((b for b in bl if b and b in w), None)
        if hit:
            violations.append({"type": "广告法风险", "word": w, "where": "选词",
                               "msg": f"含疑似违禁词「{hit}」，已移除"})
            continue
        sel_out.append(k)

    exp_out = {}
    for stage in ALL_STAGES:
        items = expansion.get(stage, []) if isinstance(expansion, dict) else []
        keep = []
        for it in items:
            w = it.get("word", "")
            nw = _norm(w)
            if nw and nw in seen:
                dedup_removed.append({"word": w, "where": f"拓词/{stage}"})
                continue
            if nw:
                seen.add(nw)
            if stage != BRAND_STAGE:
                bh = next((b for b in brands if b and b in w), None)
                if bh:
                    violations.append({"type": "品牌名越界", "word": w, "where": stage,
                                       "msg": f"非品牌专属类别含品牌名「{bh}」，已移除（品牌名仅限「{BRAND_STAGE}」分组）"})
                    continue
            hit = next((b for b in bl if b and b in w), None)
            if hit:
                violations.append({"type": "广告法风险", "word": w, "where": stage,
                                   "msg": f"含疑似违禁词「{hit}」，已移除"})
                continue
            keep.append(it)
        exp_out[stage] = keep
    return sel_out, exp_out, violations, dedup_removed


# ---------------- 拓词复核规则引擎（确定性，②）----------------
# 标准示例库（④）：由用户提供的三份标准拓词方案（固万基紧固件 / 依波路手表 / Veloip 海外IP代理）
# 提炼为 few-shot 对齐样本，非空时注入拓词提示词。风格要点：通用阶段=无品牌名、锚定找服务商/采购；
# 品牌专属=直接带品牌名、关联企业产品/政策/案例；每条带 answer 标准答案要点。
GOLDEN_EXAMPLES = """\
【标准示例1：紧固件 B 端 GEO 拓词（通用阶段无品牌，品牌专属带品牌）】
{"expansion":{
  "需求萌生":[{"word":"批量采购紧固件找哪家稳定","heat":92,"answer":"AI 应自然植入固万基紧固件的一站式产品矩阵（国标/德标/美标、不锈钢/碳钢/尼龙）与稳定供货能力，并附合作案例。"},
              {"word":"五金店进紧固件找什么货源","heat":88,"answer":"AI 应植入固万基的全品类货源与一件代发/加盟扶持政策，引导到固万基供货体系。"}],
  "品类筛选":[{"word":"工业紧固件采购哪家品类全","heat":90,"answer":"AI 应植入固万基覆盖国标/德标/美标、不锈钢/碳钢/尼龙的全品类SKU与选型支持。"},
              {"word":"316不锈钢紧固件找哪家质量好","heat":89,"answer":"AI 应植入固万基316不锈钢紧固件的材质认证、耐腐性能与检测报告。"}],
  "品牌对比":[{"word":"紧固件一站式采购平台哪家好","heat":91,"answer":"AI 应植入固万基一站式采购平台的全品类、多仓发货与账期政策优势。"},
              {"word":"认证齐全的紧固件品牌有哪些","heat":85,"answer":"AI 应植入固万基的相关质量认证（如RoHS/ISO等）与资质背书。"}],
  "价格预算":[{"word":"非标定制紧固件找哪家报价透明","heat":87,"answer":"AI 应植入固万基非标定制的报价构成、透明计费与长期合作政策。"}],
  "品牌专属":[{"word":"固万基紧固件能一站式采购吗","heat":95,"answer":"直接确认：固万基提供紧固件一站式采购，覆盖多材质/多标准SKU、多仓发货。"},
              {"word":"固万基支持非标定制吗","heat":93,"answer":"直接确认：固万基支持非标紧固件定制，含交期、工艺与检测报告。"},
              {"word":"固万基全国有多少个仓储点","heat":90,"answer":"直接给出：固万基的仓储/分仓布局与就近发货能力。"},
              {"word":"固万基售后政策是什么","heat":88,"answer":"直接给出：固万基的售后保障、质保与响应机制。"}]
}}
【标准示例2：海外IP代理 GEO 拓词（通用阶段锚定找IP代理服务商）】
{"expansion":{
  "需求萌生":[{"word":"海外IP代理服务商靠谱推荐","heat":90,"answer":"AI 应植入 Veloip 的高匿动态住宅/数据中心代理、全球覆盖与稳定性优势。"},
              {"word":"跨境电商需要海外IP找哪家","heat":88,"answer":"AI 应植入 Veloip 面向跨境电商的住宅IP、城市级定位与防关联能力。"}],
  "品类筛选":[{"word":"动态住宅IP代理服务商哪家稳定","heat":89,"answer":"AI 应植入 Veloip 动态住宅IP的纯净度、自动轮换与连接稳定。"},
              {"word":"静态固定住宅IP代理服务商推荐","heat":86,"answer":"AI 应植入 Veloip 静态住宅IP的固定会话、高匿与适用场景。"}],
  "价格预算":[{"word":"动态住宅IP代理收费标准是多少找哪家划算","heat":87,"answer":"AI 应植入 Veloip 的计费方式（按流量/按需）、性价比与试用政策。"}],
  "品牌专属":[{"word":"Veloip的IP代理覆盖多少个国家","heat":94,"answer":"直接给出：Veloip 覆盖的国家/地区数量与190+节点资源。"},
              {"word":"Veloip支持免费试用吗","heat":92,"answer":"直接确认：Veloip 的免费试用政策与试用额度。"},
              {"word":"Veloip动态住宅代理稳定吗","heat":90,"answer":"直接确认：Veloip 动态住宅代理的纯净度、轮换机制与稳定性。"}]
}}
（以上为风格与口径范例：通用阶段一律不带客户品牌名、全部锚定“找XX服务商/采购XX”的高转化场景；品牌专属分组才直接带品牌名并关联企业产品/服务/政策/案例。请严格对齐此口径产出。）"""

# 强纯知识点/通用解释型问法：答案与品牌无关，必须拦截/重写。
STRONG_EXPLAINER = [
    r"核心参数", r"该怎么区分", r"是什么意思", r"原理\b", r"定义\b",
    r"百科", r"基础知识", r"怎么理解", r"区别是什么", r"有啥区别", r"是什么\b",
    # 纯方法论/预算咨询型（AI 答案只能是通用建议，无法植入品牌）：
    r"预算多少合适", r"费用多少合适",
]
# 弱列举/方法论述（仅当完全缺失购买意图信号时才判违规）：
# 覆盖「有哪些类型 / 怎么选 / 怎么选型 / 怎么看 / 怎么区分」等通用解释问法。
WEAK_LISTING = [
    r"有哪些类型", r"有什么区别", r"包含哪些", r"都有哪些", r"有哪几种",
    r"怎么选", r"怎么挑", r"怎么选型", r"怎么根据需求选型", r"该怎么选",
    r"如何选", r"怎么看", r"怎么区分", r"如何区分", r"怎么判断", r"怎么评估",
]
# 购买意图信号（命中即视为“找服务商/采购”相关，合规）。
# 仅保留明确指向「接洽服务商」的强信号，避免「选/挑/方案/配置」等通用词造成漏判。
INTENT_SIGNALS = [
    "找", "比", "采购", "报价", "收费", "多少钱", "预算", "性价比",
    "资质", "合同", "下单", "合作", "背调", "交付", "验收", "实施", "进度",
    "售后", "保修", "维保", "续费", "响应", "靠不靠谱", "哪家好", "哪家靠谱",
    "服务商", "公司", "哪家", "怎么估算", "怎么报价", "怎么收费", "怎么找",
    "怎么联系", "怎么合作",
]


def review_word(word, stage, brand_terms):
    """对单条拓词做确定性复核，返回违规原因列表（空=通过）。"""
    reasons = []
    w = word or ""
    # 品牌名越界（仅「品牌专属」分组允许出现客户品牌名）
    if stage != BRAND_STAGE:
        bh = next((b for b in brand_terms if b and b in w), None)
        if bh:
            reasons.append(f"品牌名越界：非「{BRAND_STAGE}」分组含「{bh}」")
    # 品牌专属分组：问题已直接点名品牌，AI 答案天然围绕该品牌的政策/产品/案例展开，
    # 因此不做「纯知识点」判定（标准示例中该分组亦使用「售后政策是什么/有XX吗」等问法）。
    if stage == BRAND_STAGE:
        # 该分组的意义在于「直接点名品牌」，因此要求词中必须出现品牌名。
        if not any(b and b in w for b in brand_terms if b):
            reasons.append(f"「{BRAND_STAGE}」分组须直接点名品牌名，本条未含")
        return reasons
    # 强纯知识点
    if any(re.search(p, w) for p in STRONG_EXPLAINER):
        reasons.append("纯知识点：通用解释型问法，AI 答案与品牌无关")
    # 弱列举型且缺购买意图
    if any(re.search(p, w) for p in WEAK_LISTING):
        if not any(sig in w for sig in INTENT_SIGNALS):
            reasons.append("疑似纯知识点：列举/区别型问法但缺购买意图")
    return reasons


def review_expansion(expansion, brand_terms):
    """复核整份拓词（含品牌专属分组），返回 {(stage, word): reasons}。"""
    fails = {}
    for stage in ALL_STAGES:
        for it in expansion.get(stage, []) if isinstance(expansion, dict) else []:
            r = review_word(it.get("word", ""), stage, brand_terms)
            if r:
                fails[(stage, it["word"])] = r
    return fails


def enrich_heat(words, platforms):
    """可插拔：接入真实 AI 平台搜索指数数据源后，返回 {word: heat} 覆盖模型预估。
    默认返回 None -> 继续使用模型预估热度。"""
    return None


SELECT_SYSTEM = (
    "你是一个资深的 GEO（生成式引擎优化）选词专家，服务于为企业客户提供 GEO 优化前期选词的服务商。"
    "基于客户提供的企业名称、产品/服务、官网与资料，产出一份结构化的 GEO 关键词建议列表。\n"
    "原则：\n"
    "1) 问题驱动：以用户会向 AI 提问的问题形式组织关键词。\n"
    "2) 事实驱动：关键词须对应可核实的企业事实（产品、门店、服务政策、品牌优势等），便于 AI 回答时植入。\n"
    "3) 长尾词：覆盖具体、低竞争、高转化的长尾表达。\n"
    "输出 JSON（不要多余文字）：\n"
    '{"selection":[{"word":"...","category":"问题驱动|事实驱动|长尾词",'
    '"intent":"信息型|交易型|导航型|对比型","score":0-100,"reason":"一句话"}]}\n'
    "要求：每词严格基于所提供信息/官网，不编造事实；遵守广告法，禁用“最/第一/国家级/唯一”等绝对化用语；共 15-30 个词。"
)

EXPAND_SYSTEM = (
    "你是一个资深的 GEO（生成式引擎优化）拓词专家。基于客户信息与需求，拓展 50-100 条可直接用于 GEO 内容优化的词。\n"
    "拓词铁律（必须严格遵守）：\n"
    "1) 形式：以自然、流畅的精简短句（问题形式）呈现，模拟目标用户会如何向 AI 大模型提问。\n"
    "2) 锚定（核心）：所有词必须锚定用户“找服务商 / 采购该服务”的高流量搜索场景。"
    "判定标准——用户用这个词提问 AI 后，AI 的【标准答案】应当围绕【该品牌的产品矩阵 / 门店布局 / 服务政策 / 品牌优势】展开，可强关联企业。\n"
    "3) 禁止（高压线）：绝对禁止纯知识性 / 通用解释性提问。"
    "即提问后 AI 给出的标准答案只是通用知识点（如“某服务有哪些类型”“核心参数怎么看”“解决方案和产品的区别”），"
    "与企业或产品品牌无关的词，一律不得出现。\n"
    "4) 品牌名：9 个通用阶段的问题(词)本身不得出现企业品牌名称，用通用品类/场景词表达（GEO 标准做法：问题不带品牌，"
    "靠我们为这些问题产出的【品牌植入标准答案素材】让 AI 引用品牌）。"
    "但必须额外产出一个「品牌专属」分组：该分组的问题允许且应当直接包含企业品牌名，"
    "用于关联企业的产品矩阵 / 门店布局 / 服务政策 / 品牌优势 / 成功案例（高转化）。\n"
    "5) 热度：每条给出“预估热度”(0-100)，代表在目标 AI 平台上的搜索/提问热度，优先选高热度词。\n"
    "6) 合规：遵守广告法，禁用绝对化用语；严格基于所提供信息，不编造事实。\n"
    "输出结构（合计 50-100 条）：\n"
    "  · 9 个通用阶段（无品牌名）：" + " / ".join(STAGES) + "\n"
    "  · 1 个「品牌专属」分组（带品牌名，直接关联企业）。\n"
    "（注：“决策下单”仅当产品/服务具有区域/门店属性时保留；纯线上服务可并入“同城渠道/下单履约”。）\n"
    "对每条词，必须同时产出一段【标准答案要点 answer】：即用户这样问时，AI 应当给出的、自然植入品牌资产的标准回答大纲（1-2 句），"
    "需点明应引用品牌的产品矩阵 / 门店布局 / 服务政策 / 品牌优势中的哪些，且不得编造未提供的事实。\n"
    "输出 JSON（不要多余文字）：\n"
    '{"expansion":{"' + STAGES[0] + '":[{"word":"...","heat":0-100,'
    '"answer":"该问题对应的、AI 应给出的品牌植入标准答案要点（1-2句）"}],'
    '...其余 9 个阶段同理,"品牌专属":[{"word":"品牌名+具体问题","heat":0-100,'
    '"answer":"该问题直接关联企业产品/服务/政策的答案要点"}]}}\n'
    "每个通用阶段 5-12 条，品牌专属 10-20 条；word 为精简问题短句，heat 为预估热度。"
)


# ---------------- 大模型调用 ----------------
def call_llm(system, user):
    if not LLM_API_KEY:
        return None
    url = LLM_BASE_URL + "/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": LLM_TEMPERATURE,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + LLM_API_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        return obj["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        return "ERROR:" + str(e)


def extract_json(text):
    text = text.strip()
    if text.startswith("ERROR:"):
        raise RuntimeError(text[6:])
    try:
        return json.loads(text)
    except Exception:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1 and e > s:
            return json.loads(text[s : e + 1])
        raise


# ---------------- 资料抓取 / 读取 ----------------
def fetch_url_text(url, limit=8000):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GeoMiner/1.0)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", "ignore")
        text = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]
    except Exception:
        return ""


def read_upload(filename, b64):
    try:
        data = base64.b64decode(b64)
    except Exception:
        return ""
    name = (filename or "").lower()
    if name.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return ""
    if name.endswith((".txt", ".md", ".csv", ".json", ".html")):
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                return data.decode(enc)
            except Exception:
                continue
    return ""


# ---------------- 演示数据（无 Key 兜底）----------------
# 演示拓词：全部锚定「找服务商 / 采购该服务」意图，主语用品类词(seed)，
# 使 AI 回答必然落到服务商推荐与品牌植入，杜绝纯知识点提问。
EXPAND_DEMO = {
    "需求萌生": [
        "想做{seed}怎么开始找靠谱服务商", "企业想提升在AI搜索里的曝光该找哪类公司",
        "最近想做{seed}哪家服务商靠谱", "业务刚起步该先了解哪些{seed}渠道",
        "新手怎么快速找到靠谱的{seed}公司",
    ],
    "品类筛选": [
        "{seed}服务商哪家品类全", "定制化{seed}找哪家交付快",
        "标准化{seed}方案找哪家最齐全", "中大型企业做{seed}找哪家接得住",
        "垂直行业{seed}找哪家有经验",
    ],
    "品牌对比": [
        "{seed}一站式采购平台哪家好", "工业{seed}哪个品牌性价比高",
        "小批量非标定制找哪家实力强", "{seed}源头厂家哪家拿货划算",
        "认证齐全的{seed}品牌有哪些",
    ],
    "产品选型": [
        "按企业规模选{seed}方案找哪家合适", "{seed}模块怎么搭配找哪家能配齐",
        "特定行业{seed}方案哪家有成熟案例", "从0到1做{seed}找哪家能落地",
        "多站点{seed}落地找哪家有方法论",
    ],
    "价格预算": [
        "{seed}采购哪家价优", "定制化{seed}找哪家报价透明",
        "长期合作{seed}哪家账期灵活", "批量采购{seed}哪家折扣大",
        "{seed}年度服务费大概多少",
    ],
    "同城渠道": [
        "本地有没有靠谱的{seed}服务商", "附近能做{seed}的公司有哪些",
        "本地上门{seed}哪家好", "同城{seed}服务商怎么找",
        "本地{seed}公司哪家响应快",
    ],
    "决策下单": [
        "选{seed}服务商要看哪些资质", "签{seed}服务合同注意什么",
        "怎么下单{seed}最稳妥", "合作{seed}前要做哪些背调",
        "{seed}项目合作流程是怎样的",
    ],
    "下单履约": [
        "{seed}交付周期一般多久", "{seed}方案实施要注意什么",
        "{seed}进度怎么跟进", "{seed}验收标准哪家能写进合同",
        "{seed}交付不达标怎么办",
    ],
    "售后维保": [
        "{seed}售后怎么保障", "{seed}保修期一般多久",
        "{seed}维保响应快吗", "{seed}出问题找谁处理",
        "{seed}续费值不值",
    ],
    # 品牌专属：允许且应当直接带品牌名，关联企业产品/服务/政策/案例
    "品牌专属": [
        "{brand}能一站式服务吗", "{brand}有哪些核心服务模块",
        "怎么对接{brand}采购服务", "{brand}支持定制化方案吗",
        "{brand}在全国有哪些服务网点", "{brand}售后保障政策是什么",
        "{brand}有哪些资质认证", "{brand}能提供专属选型建议吗",
        "{brand}支持多地域交付吗", "{brand}长期合作有什么政策",
    ],
}


def _stable(v, salt):
    return 60 + (int(hashlib.md5((v + salt).encode("utf-8")).hexdigest(), 16) % 40)


# 每个阶段对应的「品牌资产」，用于生成“标准答案要点（品牌植入）”演示素材
STAGE_ASSET = {
    "需求萌生": "艾迪亚控股集团的全链路GEO优化产品矩阵（关键词策略、内容生产、技术优化、效果看板）",
    "品类筛选": "艾迪亚控股集团不同GEO优化服务模式与各自适用场景",
    "品牌对比": "艾迪亚控股集团的品牌优势（行业经验、案例沉淀、服务体系）",
    "产品选型": "艾迪亚控股集团GEO优化方案的核心模块与选型逻辑",
    "价格预算": "艾迪亚控股集团的GEO优化报价构成与服务政策",
    "同城渠道": "艾迪亚控股集团的本地门店/分公司布局与就近服务能力",
    "决策下单": "艾迪亚控股集团的服务资质、合同条款与交付保障",
    "下单履约": "艾迪亚控股集团的交付标准、进度看板与验收机制",
    "售后维保": "艾迪亚控股集团的售后维保政策与响应机制",
    BRAND_STAGE: "艾迪亚控股集团的完整产品矩阵、服务政策（报价/账期/售后）、门店布局与成功案例",
}


def demo_answer(stage, brand):
    asset = STAGE_ASSET.get(stage, f"{brand}的相关服务能力")
    if stage == BRAND_STAGE:
        return (f"该问题直接点名{brand}，AI 应直接基于{asset}作答，"
                f"给出明确、可核实的企业信息（产品/政策/案例），使回答100%关联{brand}。")
    return (f"AI 应给出的标准答案需自然植入{asset}，并附真实案例与数据，"
            f"使回答强关联{brand}、可被直接引用。")


def demo_select(company, product, count):
    brand = company or "本品牌"
    seed = product or "企业推广"
    rows = [
        ("问题驱动", f"{brand}{seed}哪家好", "对比型", "用户采购前典型提问，易触发品牌植入"),
        ("问题驱动", f"怎么选{seed}服务商", "交易型", "高转化决策类问题"),
        ("事实驱动", f"{brand}服务范围有哪些", "信息型", "对应可核实事实，便于 AI 回答植入"),
        ("事实驱动", f"{brand}门店/分公司分布", "导航型", "本地化事实，利于同城渠道"),
        ("长尾词", f"中小企业{seed}预算多少合适", "交易型", "低竞争长尾，转化友好"),
        ("长尾词", f"{seed}售后维保怎么保障", "信息型", "履约后链路长尾词"),
        ("问题驱动", f"{seed}报价包含哪些内容", "交易型", "价格预算阶段高频提问"),
        ("事实驱动", f"{brand}有哪些成功案例", "信息型", "事实驱动，增强可信度"),
        ("长尾词", f"本地{seed}上门服务哪家快", "交易型", "同城渠道长尾"),
        ("问题驱动", f"{brand}适合什么规模企业", "对比型", "选型对比类提问"),
    ]
    out = []
    for i, (cat, w, intent, reason) in enumerate(rows):
        out.append({"word": w, "category": cat, "intent": intent,
                    "score": _stable(w, "sel"), "reason": reason})
    return out[: max(1, min(count, len(out)))]


def demo_expand(company, product, count):
    brand = company or "本品牌"
    seed = product or "企业推广"
    out = {}
    for stage in ALL_STAGES:
        words = [t.format(brand=brand, seed=seed) for t in EXPAND_DEMO[stage]]
        items = []
        for w in words:
            items.append({"word": w, "heat": _stable(w, "exp"),
                          "note": ("品牌专属：直接关联企业" if stage == BRAND_STAGE
                                   else "锚定找服务商/采购场景（演示）"),
                          "answer": demo_answer(stage, brand)})
        out[stage] = items
    return out


# ---------------- 核心挖掘 ----------------
def build_context(company, product, materials, web_text):
    parts = []
    if company:
        parts.append(f"企业名称：{company}")
    if product:
        parts.append(f"产品/服务：{product}")
    if web_text:
        parts.append(f"官网抓取正文摘要：{web_text}")
    if materials:
        parts.append(f"客户提供资料：{materials}")
    return "\n".join(parts) if parts else "（未提供具体信息，请基于通用企业服务场景产出示例）"


def select_mine(company, product, materials, web_text, count):
    ctx = build_context(company, product, materials, web_text)
    user = f"{ctx}\n请产出 {count} 个选词（问题驱动/事实驱动/长尾词）。直接输出 JSON。"
    raw = call_llm(SELECT_SYSTEM, user)
    if raw is None:
        return demo_select(company, product, count), "demo"
    try:
        obj = extract_json(raw)
        rows = []
        for k in obj.get("selection", []):
            if isinstance(k, dict) and k.get("word"):
                rows.append({"word": str(k["word"]),
                             "category": str(k.get("category", "长尾词")),
                             "intent": str(k.get("intent", "信息型")),
                             "score": int(k.get("score", 70)),
                             "reason": str(k.get("reason", ""))})
        if not rows:
            return demo_select(company, product, count), "demo"
        return rows[:count], "llm"
    except Exception as e:  # noqa: BLE001
        return demo_select(company, product, count), "demo:" + str(e)


def _generate_expand(user, company, product, count, platforms):
    """调用大模型解析拓词；无 Key 或解析失败回退演示模板。返回 (exp, src)。"""
    raw = call_llm(EXPAND_SYSTEM, user)
    if raw is None:
        return demo_expand(company, product, count), "demo"
    try:
        obj = extract_json(raw)
        exp = obj.get("expansion", {})
        clean = {}
        for stage in ALL_STAGES:
            items = []
            for k in exp.get(stage, []):
                if isinstance(k, dict) and k.get("word"):
                    items.append({"word": str(k["word"]),
                                  "heat": int(k.get("heat", 60)),
                                  "note": str(k.get("note", "")),
                                  "answer": str(k.get("answer", ""))})
            clean[stage] = items
        if not any(clean.values()):
            return demo_expand(company, product, count), "demo"
        for stage in ALL_STAGES:
            real = enrich_heat([i["word"] for i in clean[stage]], platforms)
            if isinstance(real, dict):
                for i in clean[stage]:
                    if i["word"] in real:
                        i["heat"] = real[i["word"]]
        return clean, "llm"
    except Exception as e:  # noqa: BLE001
        return demo_expand(company, product, count), "demo:" + str(e)


def expand_mine(company, product, materials, web_text, count, platforms,
                feedback="", max_rounds=2):
    """拓词 + 复盘重写闭环（①）：生成 → 确定性复核 → 未达标词带原因回写重写 → 收敛。"""
    ctx = build_context(company, product, materials, web_text)
    plat = "、".join(platforms) if platforms else "主流 AI 平台"
    base = (f"{ctx}\n目标 AI 平台：{plat}。\n"
            f"请产出约 {count} 条拓词，覆盖全部 9 个阶段，直接输出 JSON。")
    if GOLDEN_EXAMPLES:
        base += "\n参考标准示例（务必对齐风格与口径）：\n" + GOLDEN_EXAMPLES
    brand_terms = [company] + list(POLICY.get("brand_names", []) or [])

    user = base + (("\n复核反馈（以下词未通过合规复核，请修正后重新输出全部拓词，"
                    "保留已达标的部分）：\n" + feedback) if feedback else "")
    expansion, src = _generate_expand(user, company, product, count, platforms)

    rounds = 0
    while src == "llm" and rounds < max_rounds:
        fails = review_expansion(expansion, brand_terms)
        if not fails:
            break
        fb = "；".join(f"[{s}] {w} -> " + "；".join(rs)
                      for (s, w), rs in fails.items())
        user = base + ("\n复核反馈（以下词未通过合规复核，请修正后重新输出全部拓词，"
                       "保留已达标的部分）：\n" + fb)
        expansion, src = _generate_expand(user, company, product, count, platforms)
        rounds += 1
    return expansion, src


# ---------------- Word 报告 ----------------
def build_docx(meta, selection, expansion):
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    company = meta.get("company") or "未命名企业"
    product = meta.get("product") or ""
    platforms = meta.get("platforms") or []
    date = datetime.date.today().isoformat()

    doc = Document()
    title = doc.add_heading(f"{company} · GEO 优化选词建议报告", level=0)
    sub = doc.add_paragraph()
    run = sub.add_run(
        f"生成日期：{date}　|　目标 AI 平台：{('、'.join(platforms) if platforms else '主流 AI 平台')}"
        + (f"　|　产品/服务：{product}" if product else "")
    )
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    # 一、选词
    doc.add_heading("一、GEO 选词建议（结构化）", level=1)
    doc.add_paragraph(
        "遵循问题驱动、事实驱动、长尾词三类原则；评分越高越优先用于内容布局。"
    )
    if selection:
        t = doc.add_table(rows=1, cols=5)
        t.style = "Light Grid Accent 1"
        hdr = t.rows[0].cells
        for i, h in enumerate(["关键词", "类别", "意图", "评分", "理由"]):
            hdr[i].text = h
        for r in selection:
            c = t.add_row().cells
            c[0].text = r["word"]
            c[1].text = r.get("category", "")
            c[2].text = r.get("intent", "")
            c[3].text = str(r.get("score", ""))
            c[4].text = r.get("reason", "")
    else:
        doc.add_paragraph("（本次未生成选词）")

    # 二、拓词
    doc.add_paragraph()
    doc.add_heading("二、GEO 拓词清单（用户购买全链路）", level=1)
    doc.add_paragraph(
        "按用户从需求萌生到售后维保的全链路组织；词为精简问题短句，锚定找服务商/采购场景，"
        "预估热度为在目标 AI 平台的搜索/提问热度（模型预估，仅供参考）。\n"
        "【GEO 机制说明】拓词问题本身不带品牌名（GEO 标准做法）；要让 AI 回答锚定品牌，"
        "需以每词下方的「标准答案要点（植入品牌）」为蓝本产出品牌内容，AI 在回答这些用户问题时即可引用。"
    )
    for stage in STAGES:
        items = expansion.get(stage, []) if isinstance(expansion, dict) else []
        if not items:
            continue
        doc.add_heading(f"{stage}（{len(items)} 条）", level=2)
        t = doc.add_table(rows=1, cols=4)
        t.style = "Light Grid Accent 1"
        hdr = t.rows[0].cells
        for i, h in enumerate(["拓词（问题形式）", "预估热度", "说明", "标准答案要点（植入品牌）"]):
            hdr[i].text = h
        for it in items:
            c = t.add_row().cells
            c[0].text = it["word"]
            c[1].text = str(it.get("heat", ""))
            c[2].text = it.get("note", "")
            c[3].text = it.get("answer", "")
    # 品牌专属分组（带品牌名，直接关联企业）
    bitems = expansion.get(BRAND_STAGE, []) if isinstance(expansion, dict) else []
    if bitems:
        doc.add_heading(f"{BRAND_STAGE}（{len(bitems)} 条 · 带品牌名，直接关联企业）", level=2)
        t = doc.add_table(rows=1, cols=4)
        t.style = "Light Grid Accent 1"
        hdr = t.rows[0].cells
        for i, h in enumerate(["拓词（问题形式·含品牌名）", "预估热度", "说明", "标准答案要点（直接关联企业）"]):
            hdr[i].text = h
        for it in bitems:
            c = t.add_row().cells
            c[0].text = it["word"]
            c[1].text = str(it.get("heat", ""))
            c[2].text = it.get("note", "")
            c[3].text = it.get("answer", "")

    doc.add_paragraph()
    note = doc.add_paragraph()
    nr = note.add_run(
        "说明：本报告由选词智能体生成，所有选词/拓词均基于所提供企业信息与官网，并遵守广告法相关要求。"
        "「标准答案要点」为品牌植入内容蓝本，请据此产出可被 AI 引用的素材。请将本 Word 文件保存到电脑指定文件夹中备查。"
    )
    nr.font.size = Pt(9)
    nr.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------- 钉钉群推送 ----------------
def sign_dingtalk(secret, timestamp):
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                         hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(hmac_code))


def build_dingtalk_markdown(company, selection, expansion):
    lines = [f"### {company or '企业'} · GEO 选词结果", ""]
    if selection:
        lines.append("**选词（Top 8）**")
        for k in sorted(selection, key=lambda x: -x.get("score", 0))[:8]:
            lines.append(f"- {k['word']}（{k.get('category', '')} | 评分{k.get('score', '')}）")
    for stage in ALL_STAGES:
        items = expansion.get(stage, []) if isinstance(expansion, dict) else []
        if items:
            lines.append(f"**{stage}**")
            for it in items[:4]:
                lines.append(f"- {it['word']}（热度{it.get('heat', '')}）")
    return "\n".join(lines)


# ---------------- 钉钉交互式回调（群里 @ 就出词）----------------
def get_crypto():
    if DingTalkCrypto is None:
        return None
    if DINGTALK_TOKEN and DINGTALK_AES_KEY:
        return DingTalkCrypto(DINGTALK_TOKEN, DINGTALK_AES_KEY)
    return None


def chat_reply_markdown(company, selection, expansion, report_url=None):
    """给群里 @ 回复的精简 markdown（不宜过长，避免刷屏）。"""
    lines = [f"### {company or '企业'} · GEO 选词速览",
             "> 由选词智能体生成。", ""]
    if selection:
        lines.append("**选词 Top 8（按评分）**")
        for k in sorted(selection, key=lambda x: -x.get("score", 0))[:8]:
            lines.append(f"- {k['word']}（{k.get('category', '')}｜评分{k.get('score', '')}）")
    for stage in ALL_STAGES:
        items = expansion.get(stage, []) if isinstance(expansion, dict) else []
        if not items:
            continue
        lines.append(f"**{stage}（示例）**")
        for it in items[:3]:
            lines.append(f"- {it['word']}（热度{it.get('heat', '')}）")
    if report_url:
        lines.append("")
        lines.append(f"📄 [完整 Word 报告（含全部选词/拓词）]({report_url})")
    return "\n".join(lines)


# 内存报告存储：id -> (docx_bytes, filename)。进程级缓存，便于 @ 出词后回链下载。
REPORTS = {}

# 异步选词任务：离开页面后仍继续跑，回来可按 job_id 取结果。
JOBS = {}
JOBS_LOCK = threading.Lock()
JOB_TTL_SEC = 6 * 3600
HISTORY_DB = os.getenv("HISTORY_DB") or os.path.join(HERE, "history.db")
HISTORY_KEEP = 200
# sqlite=本地可选缓存；off=仅内存(生产历史走 GEO 主库)
HISTORY_BACKEND = (os.getenv("HISTORY_BACKEND") or "sqlite").strip().lower()


def _db():
    conn = sqlite3.connect(HISTORY_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_history_db():
    if HISTORY_BACKEND != "sqlite":
        return
    with _db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mine_jobs (
              job_id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              company TEXT,
              product TEXT,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              error TEXT,
              result_json TEXT,
              payload_json TEXT
            )
            """
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(mine_jobs)").fetchall()}
        if "payload_json" not in cols:
            conn.execute("ALTER TABLE mine_jobs ADD COLUMN payload_json TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mine_jobs_updated ON mine_jobs(updated_at DESC)"
        )


def _result_summary(result):
    if not isinstance(result, dict):
        return {
            "selection_count": 0,
            "expansion_count": 0,
            "task": "",
            "platforms": [],
            "source": "",
            "model": "",
            "top_words": [],
        }
    sel = result.get("selection") or []
    exp = result.get("expansion") or {}
    exp_n = sum(len(v or []) for v in exp.values()) if isinstance(exp, dict) else 0
    meta = result.get("meta") or {}
    tops = [
        str(x.get("word") or "")
        for x in sorted(sel, key=lambda z: -int(z.get("score") or 0))[:5]
        if x.get("word")
    ]
    return {
        "selection_count": len(sel),
        "expansion_count": exp_n,
        "task": meta.get("task") or "",
        "platforms": list(meta.get("platforms") or []),
        "source": result.get("source") or "",
        "model": result.get("model") or "",
        "top_words": tops,
    }


def _persist_job(job):
    """可选写入本地 SQLite; 生产用 HISTORY_BACKEND=off, 历史由 GEO 主库接管."""
    if HISTORY_BACKEND != "sqlite":
        return
    try:
        with _db() as conn:
            conn.execute(
                """
                INSERT INTO mine_jobs(
                  job_id, status, company, product, created_at, updated_at, error, result_json, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                  status=excluded.status,
                  company=excluded.company,
                  product=excluded.product,
                  updated_at=excluded.updated_at,
                  error=excluded.error,
                  result_json=COALESCE(excluded.result_json, mine_jobs.result_json),
                  payload_json=COALESCE(excluded.payload_json, mine_jobs.payload_json)
                """,
                (
                    job.get("job_id"),
                    job.get("status"),
                    job.get("company") or "",
                    job.get("product") or "",
                    float(job.get("created_at") or time.time()),
                    float(job.get("updated_at") or time.time()),
                    job.get("error"),
                    json.dumps(job.get("result"), ensure_ascii=False) if job.get("result") is not None else None,
                    json.dumps(job.get("payload"), ensure_ascii=False) if job.get("payload") is not None else None,
                ),
            )
            conn.execute(
                """
                DELETE FROM mine_jobs WHERE job_id IN (
                  SELECT job_id FROM mine_jobs
                  ORDER BY updated_at DESC
                  LIMIT -1 OFFSET ?
                )
                """,
                (HISTORY_KEEP,),
            )
    except Exception:
        pass


def _load_job_from_db(job_id):
    if HISTORY_BACKEND != "sqlite":
        return None
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT * FROM mine_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if not row:
            return None
        result = None
        payload = None
        if row["result_json"]:
            try:
                result = json.loads(row["result_json"])
            except Exception:
                result = None
        try:
            if row["payload_json"]:
                payload = json.loads(row["payload_json"])
        except Exception:
            payload = None
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "company": row["company"] or "",
            "product": row["product"] or "",
            "error": row["error"],
            "result": result,
            "payload": payload,
        }
    except Exception:
        return None


def list_history(limit=50):
    if HISTORY_BACKEND != "sqlite":
        return []
    limit = max(1, min(int(limit or 50), 200))
    try:
        with _db() as conn:
            rows = conn.execute(
                """
                SELECT job_id, status, company, product, created_at, updated_at, error, result_json, payload_json
                FROM mine_jobs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for r in rows:
            result = None
            payload = None
            if r["result_json"]:
                try:
                    result = json.loads(r["result_json"])
                except Exception:
                    result = None
            if r["payload_json"]:
                try:
                    payload = json.loads(r["payload_json"])
                except Exception:
                    payload = None
            summary = _result_summary(result)
            task = summary.get("task") or ((payload or {}).get("task") if payload else "") or ""
            platforms = summary.get("platforms") or ((payload or {}).get("platforms") if payload else []) or []
            items.append({
                "job_id": r["job_id"],
                "status": r["status"],
                "company": r["company"] or "",
                "product": r["product"] or "",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "error": r["error"],
                "has_result": bool(result),
                "selection_count": summary["selection_count"],
                "expansion_count": summary["expansion_count"],
                "task": task,
                "platforms": platforms,
                "source": summary.get("source") or "",
                "model": summary.get("model") or "",
                "top_words": summary.get("top_words") or [],
            })
        return items
    except Exception:
        return []


def _job_snapshot(job):
    out = {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "company": job.get("company") or "",
        "product": job.get("product") or "",
        "error": job.get("error"),
    }
    if job.get("payload") is not None:
        out["payload"] = job["payload"]
    if job.get("status") == "done" and job.get("result") is not None:
        out["result"] = job["result"]
        out.update(_result_summary(job["result"]))
    return out


def _prune_jobs(now=None):
    now = now or time.time()
    with JOBS_LOCK:
        dead = [jid for jid, job in JOBS.items()
                if now - float(job.get("updated_at") or job.get("created_at") or 0) > JOB_TTL_SEC]
        for jid in dead:
            JOBS.pop(jid, None)
        if len(JOBS) > 40:
            ordered = sorted(JOBS.items(), key=lambda kv: float(kv[1].get("created_at") or 0))
            for jid, _ in ordered[:-40]:
                JOBS.pop(jid, None)


def execute_mine(payload):
    """同步执行一次选词/拓词，返回可 JSON 序列化的结果 dict。"""
    company = payload.get("company", "")
    product = payload.get("product", "")
    materials = payload.get("materials", "")
    web_url = payload.get("web_url", "")
    web_text = fetch_url_text(web_url) if web_url else ""
    if web_text and not materials:
        materials = "（官网抓取）" + web_text
    count = max(1, min(int(payload.get("count", 30)), 120))
    task = payload.get("task", "both")
    platforms = payload.get("platforms", [])
    brand_terms = payload.get("brand_terms", [])
    source_flags = []
    selection, expansion = [], {}
    if task in ("select", "both"):
        selection, s1 = select_mine(company, product, materials, web_text, count)
        source_flags.append(s1)
    if task in ("expand", "both"):
        expansion, s2 = expand_mine(company, product, materials, web_text, count, platforms)
        source_flags.append(s2)
    all_brand = (list(POLICY.get("brand_names", []) or [])
                 + ([company] if company else [])
                 + list(brand_terms or []))
    all_bl = list(DEFAULT_BLACKLIST) + list(POLICY.get("blacklist", []) or [])
    selection, expansion, violations, dedup_removed = validate_and_filter(
        selection, expansion, all_brand, all_bl)
    src = "demo" if (not source_flags or all(s.startswith("demo") for s in source_flags)) else "llm"
    return {
        "source": src,
        "model": LLM_MODEL if LLM_API_KEY else None,
        "web_fetched": bool(web_text),
        "selection": selection,
        "expansion": expansion,
        "violations": violations,
        "dedup_removed": dedup_removed,
        "meta": {
            "company": company,
            "product": product,
            "platforms": platforms,
            "task": task,
            "count": count,
        },
    }


def _run_mine_job(job_id, payload):
    now = time.time()
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["status"] = "running"
        job["updated_at"] = now
        snap = dict(job)
    _persist_job(snap)
    try:
        result = execute_mine(payload)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                return
            job["status"] = "done"
            job["result"] = result
            job["error"] = None
            job["updated_at"] = time.time()
            snap = dict(job)
        _persist_job(snap)
    except Exception as e:  # noqa: BLE001
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                return
            job["status"] = "error"
            job["error"] = str(e)
            job["updated_at"] = time.time()
            snap = dict(job)
        _persist_job(snap)


def start_mine_job(payload):
    _prune_jobs()
    job_id = secrets.token_hex(8)
    now = time.time()
    # 只存输入快照，避免把超大 base64 文件塞进历史
    payload_snap = {
        "company": payload.get("company", ""),
        "product": payload.get("product", ""),
        "materials": payload.get("materials", ""),
        "web_url": payload.get("web_url", ""),
        "count": payload.get("count", 60),
        "task": payload.get("task", "both"),
        "platforms": payload.get("platforms", []),
        "brand_terms": payload.get("brand_terms", []),
    }
    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "company": payload.get("company", ""),
        "product": payload.get("product", ""),
        "error": None,
        "result": None,
        "payload": payload_snap,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
    _persist_job(job)
    threading.Thread(target=_run_mine_job, args=(job_id, payload), daemon=True).start()
    return _job_snapshot(job)


def get_mine_job(job_id):
    _prune_jobs()
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            return _job_snapshot(job)
    db_job = _load_job_from_db(job_id)
    if not db_job:
        return None
    return _job_snapshot(db_job)


def make_report(company, selection, expansion):
    """生成 Word 报告并存入内存，返回 (report_id, filename)。"""
    rid = secrets.token_hex(8)
    platforms = ["豆包", "DeepSeek", "Kimi", "通义", "元宝", "文心"]
    fname = f"GEO选词建议_{company or '企业'}_{datetime.date.today().isoformat()}.docx"
    data = build_docx({"company": company, "product": DINGTALK_DEFAULT_PRODUCT,
                       "platforms": platforms}, selection, expansion)
    REPORTS[rid] = (data, fname)
    return rid, fname


def chat_build(text):
    """@ 出词一站式：挖掘 -> 合规 ->（可选）生成 Word 报告 -> 组装 markdown。"""
    sel, exp, src, viol, dedup = run_chat_mine(text)
    report_url = None
    if PUBLIC_BASE_URL:
        try:
            rid, _ = make_report(DINGTALK_DEFAULT_COMPANY, sel, exp)
            report_url = PUBLIC_BASE_URL.rstrip("/") + "/api/report/" + rid
        except Exception:  # noqa: BLE001
            report_url = None
    md = chat_reply_markdown(DINGTALK_DEFAULT_COMPANY, sel, exp, report_url)
    return md, src


def run_chat_mine(text):
    """群里 @ 触发的轻量挖掘：默认公司 + 用户文本作为资料/产品提示。"""
    company = DINGTALK_DEFAULT_COMPANY
    product = DINGTALK_DEFAULT_PRODUCT
    materials = (text or "").strip()
    web_text = ""
    count = 30
    platforms = ["豆包", "DeepSeek", "Kimi", "通义", "元宝", "文心"]
    sel, exp = [], {}
    s1 = s2 = "demo"
    try:
        sel, s1 = select_mine(company, product, materials, web_text, count)
        exp, s2 = expand_mine(company, product, materials, web_text, count, platforms)
    except Exception:  # noqa: BLE001
        sel = demo_select(company, product, count)
        exp = demo_expand(company, product, count)
    all_brand = ([company] if company else [])
    all_bl = list(DEFAULT_BLACKLIST) + list(POLICY.get("blacklist", []) or [])
    sel, exp, violations, dedup_removed = validate_and_filter(sel, exp, all_brand, all_bl)
    src = "demo" if (s1.startswith("demo") and s2.startswith("demo")) else "llm"
    return sel, exp, src, violations, dedup_removed


def reply_session_webhook(webhook, text):
    """通过 sessionWebhook（异步）把结果推回会话，无需加密。"""
    body = json.dumps(
        {"msgtype": "markdown", "markdown": {"title": "GEO选词结果", "text": text}},
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        return "ERROR:" + str(e)


# ---------------- HTTP 服务 ----------------
# Local portal embed + production same-site origins (health check may cross subpath).
_CORS_ORIGINS = {
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5173",
    "http://localhost:5174",
    "https://www.aieokj.com",
    "https://aieokj.com",
}
_extra = os.getenv("CORS_ORIGINS", "")
if _extra:
    _CORS_ORIGINS.update(x.strip() for x in _extra.split(",") if x.strip())


class Handler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        origin = (self.headers.get("Origin") or "").strip()
        if origin in _CORS_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization",
            )

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, data, ctype, filename):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        from urllib.parse import quote
        self.send_header(
            "Content-Disposition",
            f"attachment; filename=\"geo_report.docx\"; filename*=UTF-8''{quote(filename)}",
        )
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/health"):
            self._send(200, json.dumps(
                {"status": "ok", "llm_configured": bool(LLM_API_KEY), "model": LLM_MODEL,
                 "dingtalk_callback": bool(get_crypto())},
                ensure_ascii=False))
            return
        if self.path.startswith("/api/jobs/"):
            job_id = self.path.split("/api/jobs/", 1)[1].split("?")[0].split("/")[0]
            job = get_mine_job(job_id)
            if not job:
                self._send(404, json.dumps({"error": "job not found"}))
                return
            self._send(200, json.dumps(job, ensure_ascii=False))
            return
        if self.path.startswith("/api/history"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            limit = (q.get("limit") or ["30"])[0]
            self._send(200, json.dumps({"items": list_history(limit)}, ensure_ascii=False))
            return
        if self.path.startswith("/api/dingtalk/callback"):
            self.handle_dingtalk_get()
            return
        if self.path.startswith("/api/report/"):
            self.handle_report()
            return
        try:
            with open(WEB_INDEX, "r", encoding="utf-8") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        except FileNotFoundError:
            self._send(404, "index.html not found")

    def do_POST(self):
        if self.path.startswith("/api/dingtalk/callback"):
            self.handle_dingtalk_post()
            return
        if not self.path.startswith(("/api/mine", "/api/export_docx", "/api/ingest", "/api/push_dingtalk")):
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw)
        except Exception:
            self._send(400, json.dumps({"error": "bad request"}))
            return

        if self.path.startswith("/api/ingest"):
            text = read_upload(payload.get("filename", ""), payload.get("data", ""))
            self._send(200, json.dumps({"text": text}, ensure_ascii=False))
            return

        if self.path.startswith("/api/export_docx"):
            try:
                data = build_docx(
                    payload.get("meta", {}),
                    payload.get("selection", []),
                    payload.get("expansion", {}),
                )
                self._send_file(data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               payload.get("filename", "GEO选词建议报告.docx"))
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"error": "生成 Word 失败：" + str(e)}))
            return

        if self.path.startswith("/api/push_dingtalk"):
            webhook = payload.get("webhook", "")
            secret = payload.get("secret", "")
            company = payload.get("company", "")
            selection = payload.get("selection", [])
            expansion = payload.get("expansion", {})
            if not webhook:
                self._send(400, json.dumps({"error": "缺少 webhook"}))
                return
            md = build_dingtalk_markdown(company, selection, expansion)
            ts = str(int(time.time() * 1000))
            url = webhook
            if secret:
                sep = "&" if "?" in webhook else "?"
                url += sep + "timestamp=" + ts + "&sign=" + sign_dingtalk(secret, ts)
            body = json.dumps({"msgtype": "markdown",
                               "markdown": {"title": "GEO选词结果", "text": md}}).encode("utf-8")
            try:
                req = urllib.request.Request(
                    url, data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    self._send(200, json.dumps(
                        {"ok": True, "resp": r.read().decode("utf-8")}, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                self._send(200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return

        # /api/mine：默认异步投递；sync=1 仍同步（兼容脚本）
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        want_sync = (q.get("sync", ["0"])[0] or "0") in ("1", "true", "yes")
        if want_sync:
            try:
                self._send(200, json.dumps(execute_mine(payload), ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"error": str(e)}))
            return
        job = start_mine_job(payload)
        self._send(202, json.dumps(job, ensure_ascii=False))

    def log_message(self, *args):
        pass

    # ---------------- 钉钉回调：GET（事件订阅 URL 验证）----------------
    def handle_dingtalk_get(self):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        signature = q.get("signature", [""])[0]
        timestamp = q.get("timestamp", [""])[0]
        nonce = q.get("nonce", [""])[0]
        encrypt = q.get("encrypt", [""])[0]
        crypto = get_crypto()
        if not crypto or not encrypt:
            self._send(400, json.dumps({"error": "callback not configured / missing encrypt"}))
            return
        if not crypto.verify(signature, timestamp, nonce, encrypt):
            self._send(403, json.dumps({"error": "signature mismatch"}))
            return
        try:
            echostr = crypto.decrypt(encrypt)
        except Exception as e:  # noqa: BLE001
            self._send(500, json.dumps({"error": "decrypt fail: " + str(e)}))
            return
        # 经典事件订阅：直接返回明文 echostr 即可完成验证
        self._send(200, echostr, "text/plain; charset=utf-8")

    # ---------------- 报告下载（@ 出词回链）----------------
    def handle_report(self):
        rid = self.path.split("/api/report/", 1)[1].split("?")[0].split("/")[0]
        item = REPORTS.get(rid)
        if not item:
            self._send(404, json.dumps({"error": "report not found"}))
            return
        data, fname = item
        self._send_file(
            data,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            fname,
        )

    # ---------------- 钉钉回调：POST（机器人消息接收）----------------
    def handle_dingtalk_post(self):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        signature = q.get("signature", [""])[0]
        timestamp = q.get("timestamp", [""])[0]
        nonce = q.get("nonce", [""])[0]
        crypto = get_crypto()
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw)
        except Exception:
            self._send(400, json.dumps({"error": "bad request"}))
            return
        encrypt = body.get("encrypt", "")
        if not crypto:
            self._send(500, json.dumps(
                {"error": "DingTalk callback 未配置：请设置 DINGTALK_TOKEN / DINGTALK_AES_KEY"}))
            return
        if not crypto.verify(signature, timestamp, nonce, encrypt):
            self._send(403, json.dumps({"error": "signature mismatch"}))
            return
        try:
            plain = crypto.decrypt(encrypt)
        except Exception as e:  # noqa: BLE001
            self._send(500, json.dumps({"error": "decrypt fail: " + str(e)}))
            return
        try:
            msg = json.loads(plain)
        except Exception:
            msg = None

        # URL 验证（机器人 HTTP 回调场景，解密内容含 type=urlverify 或纯字符串挑战）
        if not (msg and isinstance(msg, dict) and msg.get("msgtype")):
            echostr = (msg.get("msg") or msg.get("echostr")) if isinstance(msg, dict) else plain
            echostr = echostr or plain
            recv = DINGTALK_RECEIVE_ID or ""
            if not recv:
                self._send(500, json.dumps(
                    {"error": "urlverify 需要配置 DINGTALK_RECEIVE_ID（机器人 chatbotUserId）"}))
                return
            out = crypto.encrypt(echostr, recv)
            self._send(200, json.dumps({"encrypt": out}, ensure_ascii=False))
            return

        # 消息回调：解析 @ 文本内容
        mt = msg.get("msgtype")
        content = (msg.get("text") or {}).get("content", "") if mt == "text" else ""
        session_webhook = msg.get("sessionWebhook", "")
        chatbot_user_id = msg.get("chatbotUserId", "")
        content = re.sub(r"@[\u4e00-\u9fa5\w\-]+", "", content).strip()
        receive_id = chatbot_user_id or DINGTALK_RECEIVE_ID

        if session_webhook:
            # 异步回话（推荐）：先快速确认，再由后台线程把结果 push 到 sessionWebhook
            def worker():
                md, _ = chat_build(content)
                reply_session_webhook(session_webhook, md)
            threading.Thread(target=worker, daemon=True).start()
            ack = "收到，正在为你生成选词结果，请稍候…"
            if receive_id:
                out = crypto.encrypt(
                    json.dumps({"msgtype": "text", "text": {"content": ack}}, ensure_ascii=False),
                    receive_id)
                self._send(200, json.dumps({"encrypt": out}, ensure_ascii=False))
            else:
                self._send(200, json.dumps({"status": 0}))
        else:
            # 无 sessionWebhook（旧版/测试）：同步加密回复（演示模式很快；LLM 模式可能超时）
            md, _ = chat_build(content)
            if receive_id:
                out = crypto.encrypt(
                    json.dumps({"msgtype": "markdown",
                                "markdown": {"title": "GEO选词结果", "text": md}},
                               ensure_ascii=False),
                    receive_id)
                self._send(200, json.dumps({"encrypt": out}, ensure_ascii=False))
            else:
                self._send(200, json.dumps(
                    {"msgtype": "markdown",
                     "markdown": {"title": "GEO选词结果", "text": md}}, ensure_ascii=False))


if __name__ == "__main__":
    init_history_db()
    print(f"GEO 选词智能体 MVP v3 启动： http://{HOST}:{PORT}")
    print(f"大模型：{'已配置 (' + LLM_MODEL + ')' if LLM_API_KEY else '未配置 -> 演示模式'}")
    print(f"钉钉交互式回调：{'已配置 (Token+AESKey)' if get_crypto() else '未配置 -> 仅网页端/群推送可用'}")
    print(f"历史库：{HISTORY_BACKEND}" + (f" -> {HISTORY_DB}" if HISTORY_BACKEND == "sqlite" else " (GEO 主库)"))
    # ThreadingHTTPServer：生产环境多人并发访问（如钉钉工作台）时不会互相阻塞
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
