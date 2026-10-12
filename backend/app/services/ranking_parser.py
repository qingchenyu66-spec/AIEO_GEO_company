"""Parse brand ranks from AI answers: category-local rank first, else appearance order."""

from __future__ import annotations

import re
from typing import Any, Callable

from app.services.report_text_sanitize import sanitize_entity_name

CIRCLE_NUM_MAP = {
    "①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5,
    "⑥": 6, "⑦": 7, "⑧": 8, "⑨": 9, "⑩": 10,
    "⑪": 11, "⑫": 12,
}

CHINESE_NUM_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

LIST_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"(\d+)\s*[\.、．\)）]|"
    r"[（(](\d+)[)）]|"
    r"([①②③④⑤⑥⑦⑧⑨⑩⑪⑫])"
    r")\s*(.+)$"
)

BULLET_ITEM_RE = re.compile(r"^[-•·▪]\s*(.+)$|^\*(?!\*)\s*(.+)$")

PROSE_RANK_RE = re.compile(
    r"第([一二三四五六七八九十\d]+)[个位名项]?[，,：:\s]+([^，,。；;\n]{2,50})"
)

MARKDOWN_HEADER_RE = re.compile(r"^(#+)\s*(.+)$")
NUMBERED_TITLE_RE = re.compile(r"^(\d+)\s*[\.、．]\s*(.+)$")
SECTION_TITLE_RE = re.compile(r"^[一二三四五六七八九十百]+[、.．]\s*\S")

SUBSECTION_LABELS = frozenset({
    "特点", "适用", "适用人群", "优势", "短板", "劣势", "特色", "定位", "覆盖", "适合",
    "核心场景", "覆盖规模", "核心优势", "服务能力", "服务", "资源", "资源能力",
    "投放建议", "快速选型", "核心能力", "适配场景", "覆盖面", "适用场景", "适合场景",
    "资质", "资质层面", "规模", "规模体量", "价格", "价格水平", "报价", "案例",
    "客户", "客户群", "要点", "建议", "总结", "对比", "说明", "简介", "劣势短板",
    "核心覆盖", "核心资源", "核心服务", "产品能力", "技术能力", "团队能力",
    "渠道能力", "品牌能力", "服务体系", "资源体系", "核心亮点", "主要优势",
    "资源覆盖", "服务特色", "特色服务", "适合客户", "适合对象", "适合需求",
    "覆盖范围", "服务范围", "服务优势", "服务特点", "资源规模", "资源真实性",
    "核心资质", "业务覆盖",
    # 公司详情 / 选型段标题（常见被误当成选手）
    "成立时间", "注册资金", "一站式服务", "标杆项目", "全链条资质", "生产设备齐全",
    "选择建议", "补充推荐", "选择要点", "按需求类型选", "核实资质", "看案例",
    "价格透明", "媒体资源型", "技术创新型",
})
# 公司详情字段名：资质层面 / 规模体量 / XX能力 / XX优势… — 不是选手
_FIELD_LABEL_RE = re.compile(
    r"^("
    r"(?:核心|主要)?"
    r"(?:优势|亮点|短板|劣势|特点|特色|定位|资源|服务|能力|规模|价格|报价|"
    r"案例|客户|资质|要点|建议|总结|对比|说明|简介|覆盖|适合|适用)"
    r"(?:能力|层面|维度|方面|体量|水平|优势|体系|群|场景|规模|范围|覆盖|"
    r"特色|真实性|对象|需求|客户|亮点)?"
    r"|(?:适用|适合|适配)(?:场景|客户|对象|需求|人群)"
    r"|(?:服务|资源|产品|渠道|品牌|技术|团队)"
    r"(?:能力|特色|特点|优势|规模|范围|覆盖|体系|真实性)"
    r"|投放建议|快速选型|覆盖面|覆盖规模|覆盖范围"
    r"|成立时间|注册资金|一站式服务|标杆项目|全链条资质|生产设备齐全"
    r"|选择建议|补充推荐|选择要点|按需求类型选"
    r")$"
)
# 「一、广州伟源光电科技有限公司」= 选手；「一、电梯广告公司」= 分类
# 「艾迪亚控股集团」等无「有限公司」后缀的简称也要认成选手
_COMPANY_ENTITY_HINT_RE = re.compile(
    r"(有限公司|股份有限公司|有限责任公司|集团有限|控股集团|集团$|股份公司|（集团）|株式会社|"
    r"Co\.,?\s*Ltd\.?|Inc\.?)"
)
# 学科/学习项误入榜（教育类正文），不当作公司
_NON_COMPANY_TOKENS = frozenset({
    "语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治",
    "单词", "作文", "阅读", "听力", "口语", "语法", "古诗", "文言文",
    # 选型 checklist / 决策步骤 / 行业标签词，不是公司名
    "需求定义", "实地考察", "试点验证", "行业经验", "语种能力", "合规资质",
    "交付模式", "成本结构", "技术能力", "数据安全", "弹性", "资质",
    "金融", "保险", "电商", "通讯", "出海", "新零售", "跨境电商",
})
_SUBCATEGORY_HINTS = (
    "大厂", "工程商", "运营商", "代理商", "服务商", "制造商", "厂家", "媒体",
    "头部", "区域", "性价比", "上市", "量产", "工程", "本地",
    # 元宝「按梯队」：🥇一线 / 🥈本土全国代理 / 🥉策略购买型
    "一线", "二线", "三线", "梯队", "持有方", "全国代理", "购买型", "自营",
    # 2026-08-18 - ### 3. 中国本土市场活跃榜单 被当选手，后续 bullet 被 in_company_block 吞掉
    "榜单", "巨头", "冠军", "赛道", "本土",
    "综合代理商", "选购决策", "小贴士",
)
_TIER_MEDAL_RE = re.compile(r"^[🥇🥈🥉🏅]\s*")


_REGION_LABEL_RE = re.compile(
    r"^(?:"
    r"华东|华南|华西|华北|华中|西南|西北|东北|东南|其他|其他强市|本地|全国|"
    r"北京|上海|广州|深圳|杭州|成都|重庆|武汉|西安|南京|天津|苏州|济南|合肥|"
    # 须带省/市/区；不可选后缀，否则「利亚德」「艾比森」会被当成地区
    r"[\u4e00-\u9fff]{1,3}(?:省|市|区)"
    r")$"
)
_SCENE_SUBSECTION_RE = re.compile(
    r"(?:单城市深耕|多城市全国统投|多城.*统投|候车亭/灯箱|候车亭.*灯箱)"
)
_ROLE_LABEL_BULLET_RE = re.compile(r"^(?:区域型|整合代理|资源型|代理型)\s*[：:]")
_NON_RANK_CATEGORY_HINTS = (
    "判断标准", "挑选", "如何选", "怎么选", "注意事项", "总结", "结语",
    "核心判断", "选型建议", "快速对照", "快速参考", "对照",
    "关键考量", "决策路径", "评估", "checklist", "Checklist",
    "下一步", "建议的下一步", "维度", "关键问题",
    "补充推荐", "选择要点", "案例总结",
    # 2026-08-17 - 「简单选购建议」下编号项被当品牌 → 榜尾脏行撑到第18
    "选购建议", "简单选购", "购买建议", "选购要点",
    "排名陷阱", "必须警惕", "选购决策", "小贴士",
)
_SENTENCE_NAME_HINTS = (
    "有优势", "而不", "优先问", "好的公司", "能否提供", "在一线", "适合区域", "适合全国",
    "→", "->", "只投", "预算有限",
    "擅长", "售后", "漏刊", "无多层", "案例极", "审批", "上刊", "运维", "补刊",
    "授权", "转包", "监测", "落地",
)
_CORP_NAME_HINTS = (
    "公司", "集团", "控股", "股份", "有限", "传媒", "广告", "媒体", "科技", "网络",
    "商社", "银行", "证券", "保险", "医院", "大学", "学院",
)
# 适用客户/行业类型整词，不是选手（「招商银行」等实体名仍可过）
_CUSTOMER_TYPE_TOKENS = frozenset({
    "政府", "初创公司", "教育平台", "AI公司", "社交媒体", "大促期间",
    "中小互联网企业", "本地生活平台", "直播平台", "电商", "金融机构",
})
# DeepSeek 分享页：引用写成 -\\nN\\n- 链，不是 [citation:N]
_SHARE_CITATION_CHAIN_RE = re.compile(
    r"-(?:\s*\n\s*\d{1,3}\s*\n\s*-)+\s*\n\s*\d{1,3}(?=\s*(?:\n|$))",
)
_SHARE_CITATION_SINGLE_RE = re.compile(r"(?<=\S)-\s*\n\s*\d{1,3}(?=\s*\n)")


def _strip_share_page_citation_markers(text: str) -> str:
    """去掉分享页 -\\n数字\\n- 引用碎行，避免打断 TSV / 被当成 bullet 选手。

    2026-09-03 - DeepSeek「。-\\n2」被 layout 拆成「- 2」→ 鸿联九五 structured 第2
    """
    value = str(text or "")
    prev = None
    while prev != value:
        prev = value
        value = _SHARE_CITATION_CHAIN_RE.sub("", value)
        value = _SHARE_CITATION_SINGLE_RE.sub("", value)
    # 链拆剩的孤立数字行（保留「1. 公司」编号项）
    value = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", value)
    return value


def _normalize_answer_layout(text: str) -> str:
    """Split inline bullets / headers crushed onto one line (yuanbao/doubao HTML export)."""
    # 2026-07-30 - markdown 表格内 <br> 若先剥成换行会拆断 | 行，品牌表只剩首行
    # 2026-09-20 - <0.3% ... 合格率> 不是标签, 只剥以字母开头的标签
    normalized = re.sub(r"<br\s*/?>", " ", text or "", flags=re.I)
    normalized = re.sub(r"</?[A-Za-z][^>]*>", "\n", normalized)
    normalized = re.sub(r"\r", "\n", normalized)
    # 须在「句号后 - 拆 bullet」之前，否则 。-\\n2 会变成 - 2 选手
    normalized = _strip_share_page_citation_markers(normalized)
    # 元宝分享页：孤立「•」行后接「公司名：说明」——合成可解析 bullet
    # ponytail: 只合并空子弹行；编号清单 1.\\n1.\\n 另案，避免把「点位权属」抬成选手
    normalized = re.sub(
        r"(?m)^(?:[•·▪]\s*\n)+\s*(?=\S)",
        "- ",
        normalized,
    )
    # 粘连标题：`...[citation:5]## 下一节` 与 `...科技。##户外大屏` / `##二、全国`
    # ponytail: 行首正常标题不动；只拆「非空白后紧跟的 ##～######」
    normalized = re.sub(r"(?<=[^\s#\n])(#{2,6})(?=\s*\S)", r"\n\1", normalized)
    normalized = re.sub(r"(\[[^\]]*\])\s*-\s*", r"\1\n- ", normalized)
    normalized = re.sub(r"(?<=[。；！？])-\s*", "\n- ", normalized)
    # ponytail: `-**Name**` / `...- **Name**` without newline
    normalized = re.sub(r"(?<=\S)-\s*\*\*", "\n- **", normalized)
    normalized = re.sub(r"(?<=\S)-\s+(?=\*\*)", "\n- ", normalized)
    return normalized


def _clean_item_name(text: str) -> str:
    value = re.sub(r"\*\*", "", text or "")
    value = re.sub(r"\[\[[^\]]+\]\]", "", value)
    value = re.sub(r"\[[^\]]+\]\([^)]+\)", "", value)
    value = re.sub(r"\[citation:\d+\]", "", value, flags=re.I)
    value = re.sub(r"^[*·•▪]+", "", value.strip())
    value = re.sub(r"^[「『\"'“]+|[」』\"'”]+$", "", value.strip())
    value = re.sub(r"[（(].*?[)）]$", "", value.strip())
    # 2026-09-03 - 引用掐断后公司格残留「鸿联九五-」
    value = re.sub(r"[：:，,;；\.。\-]+$", "", value.strip())
    return value.strip()


def _has_company_entity_signal(name: str) -> bool:
    """公司/集团/传媒等实体信号——详情字段（总部/联系方式）没有。"""
    cleaned = str(name or "").strip()
    if not cleaned:
        return False
    if _COMPANY_ENTITY_HINT_RE.search(cleaned):
        return True
    return any(hint in cleaned for hint in _CORP_NAME_HINTS)


def _is_metadata_field_label(name: str) -> bool:
    """公司详情字段（联系方式/总部/官网…），不是选手。

    2026-08-24 - 不靠逐个加词；无实体信号 + 字段族后缀即挡
    """
    cleaned = str(name or "").strip()
    if not cleaned:
        return True
    if _is_subsection_label(cleaned) or cleaned in SUBSECTION_LABELS:
        return True
    if _FIELD_LABEL_RE.match(cleaned):
        return True
    if _has_company_entity_signal(cleaned):
        return False
    if re.fullmatch(
        r"[\u4e00-\u9fffA-Za-z0-9]{1,8}(?:方式|热线|电话|官网|网址|邮箱|微信|地址)",
        cleaned,
    ):
        return True
    if cleaned in {"总部", "电话", "地址", "官网", "网址", "邮箱", "微信", "热线"}:
        return True
    return False


def _bullet_field_value(body: str) -> str:
    """`- **标签**：值` → 冒号后正文（去引用）。"""
    text = str(body or "")
    parts = re.split(r"[：:]", text, maxsplit=1)
    if len(parts) < 2:
        return ""
    value = re.sub(r"\[citation:\d+\]", "", parts[1], flags=re.I)
    value = re.sub(r"\*\*", "", value)
    return value.strip()


def _is_peer_company_bullet(name: str, body: str) -> bool:
    """公司详情块内：同段新公司 bullet 才放行；字段 bullet 继续跳过。

    2026-08-24 - 有实体信号直接放行；无信号则靠长描述区分「白马户外：…」与「总部：北京」
    """
    if not name or not _looks_like_company_list_name(name):
        return False
    if _is_metadata_field_label(name):
        return False
    if _has_company_entity_signal(name):
        return True
    value = _bullet_field_value(body)
    if len(value) < 18:
        return False
    if re.match(r"^(官网|电话|服务热线|https?://|www\.|[\d\-＋+\s]{6,})", value, re.I):
        return False
    return True


def _looks_like_company_list_name(name: str) -> bool:
    cleaned = str(name or "").strip()
    if not cleaned or len(cleaned) > 40:
        return False
    # 2026-09-03 - 引用碎行「2」「1」不当选手（鸿联九五被挤成 structured 第2）
    if cleaned.isdigit() or re.fullmatch(r"\d{1,3}", cleaned):
        return False
    if _is_subsection_label(cleaned) or cleaned in SUBSECTION_LABELS:
        return False
    # 递归注意：_is_metadata_field_label 会再调 subsection；字段族在此挡「联系方式」
    if cleaned in {"总部", "电话", "地址", "官网", "网址", "邮箱", "微信", "热线"}:
        return False
    if not _has_company_entity_signal(cleaned) and re.fullmatch(
        r"[\u4e00-\u9fffA-Za-z0-9]{1,8}(?:方式|热线|电话|官网|网址|邮箱|微信|地址)",
        cleaned,
    ):
        return False
    if cleaned in _NON_COMPANY_TOKENS:
        return False
    # 整词「银行/政府/公司」是客户类型或后缀提示，不是选手名
    if cleaned in _CORP_NAME_HINTS or cleaned in _CUSTOMER_TYPE_TOKENS:
        return False
    # A 类 / B类 / 区域强者 — 分类标签，不是选手
    if re.fullmatch(r"[A-Za-zＡ-Ｚａ-ｚ]?\s*类", cleaned) or cleaned.endswith("类") and len(cleaned) <= 4:
        return False
    if cleaned in {"区域强者", "全国强者", "本地强者", "行业强者"}:
        return False
    if "→" in cleaned or "->" in cleaned:
        return False
    if any(hint in cleaned for hint in _SENTENCE_NAME_HINTS):
        return False
    if any(ch in cleaned for ch in "，。；！？"):
        return False
    if cleaned.startswith("看") and "：" not in cleaned:
        return False
    # 2026-08-17 - 选购建议「追求极致质感 / 想要进口质感 / 厨卫潮湿区域」误进榜
    if re.match(r"^(追求|想要|看重|优先)", cleaned):
        return False
    if cleaned.endswith("区域") and not any(hint in cleaned for hint in _CORP_NAME_HINTS):
        return False
    # 2026-08-17 - 广告答字段名/避坑句进结构化榜
    if cleaned in {
        "地址", "电话", "业务范围", "本地优势", "适合对象", "全媒体平台", "服务能力",
        "资源覆盖", "客户口碑", "推荐理由", "核心资源", "核心优势", "资源规模",
        "业务覆盖",
        "技术亮点", "成本优势", "灵活性", "组合投放", "注重互动", "明确目标",
        "-", "—",
    }:
        return False
    # 2026-08-24 - 「注意：区分福人家居…」被当选手 → 国产主流大王椰 7→8；挡提示语前缀
    if cleaned.startswith(("不要", "确认", "注重", "明确", "核实", "注意", "提醒")):
        return False
    # 2026-08-17 - 「防潮和防霉」「铁路局媒介资源」「深圳宝安、天津…」误占类内槽
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}[和与][\u4e00-\u9fff]{2,4}", cleaned) and not any(
        hint in cleaned for hint in _CORP_NAME_HINTS
    ):
        return False
    # 2026-08-19 - 「华兴人力资源」被当资源踢出 → 垂直专家鸿联从第4吃成第3
    if (
        cleaned.endswith("资源")
        and not cleaned.endswith("人力资源")
        and not any(hint in cleaned for hint in _CORP_NAME_HINTS)
    ):
        return False
    if re.search(r"[、，,]", cleaned) and not any(hint in cleaned for hint in _CORP_NAME_HINTS):
        return False
    if re.search(r"清单|匹配|指标|交付|全包|抽查|监播|形式匹配", cleaned):
        return False
    # 长句且无公司后缀 → 描述文案，不是选手
    if len(cleaned) > 14 and not any(hint in cleaned for hint in _CORP_NAME_HINTS):
        return False
    return True


def _strip_numbered_heading_prefix(content: str) -> str | None:
    """Strip 一、 / 1. prefix; return body or None if not numbered."""
    text = str(content or "").strip()
    match = re.match(r"^[一二三四五六七八九十百]+[、.．]\s*(.+)$", text)
    if match:
        return match.group(1).strip()
    numbered = NUMBERED_TITLE_RE.match(text)
    if numbered:
        return numbered.group(2).strip()
    return None


def _company_from_numbered_heading(content: str) -> str | None:
    """「一、广州伟源光电科技有限公司（…）」→ 公司名；「一、电梯广告公司」→ None（分类）。"""
    body = _strip_numbered_heading_prefix(content)
    if not body:
        return None
    name = re.split(r"[（(]", body, maxsplit=1)[0].strip()
    name = _clean_item_name(name)
    if not name or _is_subsection_label(name) or name in SUBSECTION_LABELS:
        return None
    if not _COMPANY_ENTITY_HINT_RE.search(name):
        return None
    if not _looks_like_company_list_name(name):
        return None
    return name


def _nominees_from_pipe_numbered_heading(content: str) -> list[str] | None:
    """### 7）大王椰｜生态板 / ### 7.大王椰｜… / ### 7）大王椰、伟业 → 档内选手名。

    2026-08-24 - 无「有限公司」后缀的板材品牌编号标题也要进父级 ## 段计数
    仅阿拉伯数字编号；中文「二、」仍是 ## 分段标题
    """
    text = _TIER_MEDAL_RE.sub("", str(content or "").strip()).strip()
    text = re.sub(r"\[citation:\d+\]", "", text, flags=re.I).strip()
    match = re.match(r"^(\d+)\s*[、.．)）]\s*(.+)$", text)
    if not match:
        return None
    body = match.group(2).strip()
    # ｜ 后是品类/卖点，不当选手；子类判断只看品牌侧，避免「千年舟｜高性价比一线」被一线误杀
    brand_part = re.split(r"[｜|]", body, maxsplit=1)[0].strip()
    brand_part = re.sub(r"[（(][^）)]*[)）]", "", brand_part).strip()
    if not brand_part:
        return None
    if _is_non_rank_category(brand_part) or _looks_like_subcategory_header(brand_part):
        return None
    if "、" in brand_part or "，" in brand_part:
        parts = re.split(r"[、，,]", brand_part)
    else:
        parts = [brand_part]
    names: list[str] = []
    for part in parts:
        cleaned = _clean_item_name(part)
        if not cleaned:
            continue
        if _is_subsection_label(cleaned) or cleaned in SUBSECTION_LABELS:
            continue
        if _looks_like_company_list_name(cleaned) or (
            2 <= len(cleaned) <= 12 and not any(ch in cleaned for ch in "，。；！？：:")
        ):
            names.append(cleaned)
    return names or None


def _looks_like_store_list_name(name: str) -> bool:
    """门店/地址行：不当品牌选手（品牌授权门店清单里的 1.xx店）。"""
    cleaned = str(name or "").strip()
    if not cleaned:
        return False
    if re.search(r"(运营中心|专卖店|旗舰店|总代理)$", cleaned) and any(
        hint in cleaned for hint in ("板材", "涂料", "传媒", "广告", "集团", "公司", "木业", "家居", "饰材", "全屋")
    ):
        return False
    # 装饰城店｜地址 — 仍是门店
    head = re.split(r"[｜|]", cleaned, maxsplit=1)[0].strip()
    if re.search(r"(整家店|家居店|装饰城店|商场店|体验店)$", head):
        return True
    if head.endswith("店") and not any(hint in head for hint in _CORP_NAME_HINTS):
        return True
    if re.search(r"[路街巷号区楼层]\d|\d号|地铁站", cleaned):
        return True
    return False


def _looks_like_geo_place_label(name: str) -> bool:
    """地理分区/市场集散地标题：划定列表范围，不是品牌选手。

    2026-08-24 - 城关区/婺城区·建材市场/东阳市 误占榜导致门店推荐 rank 前移
    """
    cleaned = str(name or "").strip()
    if not cleaned:
        return False
    if re.match(r"^[\U0001F300-\U0001FAFF\U00002600-\U000027BF]", cleaned):
        return True
    core = re.sub(r"[（(][^）)]*[)）]", "", cleaned).strip()
    core = re.sub(r"\[citation:\d+\]", "", core, flags=re.I).strip()
    if "·" in core and re.search(r"(?:区|县|市|镇|新区|乡|街道)·", core):
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{2,10}(?:区|县|市|州|盟|新区)$", core):
        if not any(hint in core for hint in _CORP_NAME_HINTS):
            return True
    if re.search(r"(?:建材市场|建材城|博览城|家居城|装饰城|大市场|批发市场|商业城)$", core):
        if not any(hint in core for hint in ("板材", "涂料", "传媒", "广告", "集团", "公司", "木业")):
            return True
    if cleaned.startswith(("问清楚", "优先选", "认准", "散户", "量大")):
        return True
    return False


def _is_non_rank_category(category: str | None) -> bool:
    text = str(category or "").strip()
    return bool(text) and any(hint in text for hint in _NON_RANK_CATEGORY_HINTS)


def _extract_list_item_name(text: str) -> str:
    """Extract company name from bullet: **公司**：说明 / 西南：公司 / 公司：说明."""
    # 2026-08-24 - 勿用裸 * 剥列表符，否则 **福人** 被吃成 *福人**，加粗名丢失
    raw = re.sub(r"^[-•·▪]\s+", "", (text or "").strip())
    raw = re.sub(r"^\*(?!\*)\s+", "", raw)
    # **公司名** / **公司名**：说明（优先，避免被「地区：公司」规则抢成描述句）
    bold = re.match(r"^\*\*([^*]+)\*\*", raw)
    if bold:
        company = re.split(r"[（(]", bold.group(1).strip())[0].strip()
        # ⭐标签 / 评星后缀不当进名字
        company = re.split(r"[⭐★☆]", company, maxsplit=1)[0].strip()
        company = re.split(r"[、，,/／]", company)[0].strip()
        cleaned = _clean_item_name(company)
        if cleaned:
            return cleaned
    # 西南：艾迪亚控股 — 仅当冒号前是地区/城市短标签
    region_match = re.match(r"^([^：:\n]{1,10})[：:]\s*(.+)$", raw)
    if region_match:
        head = _clean_item_name(region_match.group(1))
        if head and _REGION_LABEL_RE.match(head):
            tail = region_match.group(2).strip()
            tail = re.split(r"[（(]", tail)[0].strip()
            company = re.split(r"[、，,/／]", tail)[0].strip()
            cleaned = _clean_item_name(company)
            if cleaned:
                return cleaned
    # 公司名：长说明 → 取冒号前
    if "：" in raw or ":" in raw:
        head = re.split(r"[：:]", raw, maxsplit=1)[0].strip()
        head = re.split(r"[（(]", head)[0].strip()
        company = re.split(r"[、，,/／]", head)[0].strip()
        cleaned = _clean_item_name(company)
        if cleaned:
            return cleaned
    return _clean_item_name(raw)


def _parse_rank_token(token: str | None) -> int | None:
    text = str(token or "").strip()
    if not text:
        return None
    if text in CIRCLE_NUM_MAP:
        return CIRCLE_NUM_MAP[text]
    if text.isdigit():
        try:
            return int(text)
        except ValueError:
            return None
    if len(text) == 1 and text in CHINESE_NUM_MAP:
        return CHINESE_NUM_MAP[text]
    if text.startswith("十") and len(text) == 2 and text[1] in CHINESE_NUM_MAP:
        return 10 + CHINESE_NUM_MAP[text[1]]
    return None


def _coerce_rank_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return None
    parsed = _parse_rank_token(text)
    if parsed is not None:
        return parsed
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    # 2026-08-12 - 分享页荣誉碎行「-」勿当 markdown 表行，否则会掐断 TSV 品牌表
    if "|" not in stripped:
        return False
    if stripped.startswith("|") and "|" in stripped[1:]:
        return True
    return bool(re.match(r"^[\|\s:\-]+$", stripped))


def _is_table_separator_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return bool(re.match(r"^[\|\s:\-]+$", stripped))


def _split_markdown_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


_TABLE_COMPANY_HEADERS = (
    "企业名称",
    "公司名称",
    "公司名",
    "品牌名称",
    "机构名称",
    "代表公司",
    "代表厂商",
    "推荐公司",
    "推荐选择",
    "供应商",
    "服务商",
    "供应商梯队",
    # 2026-08-12 - DeepSeek「系统名称|核心特点」产品表未认公司列 → 动码吃不到主表第5
    "系统名称",
    "产品名称",
    "产品名",
    "软件名称",
)
_TABLE_COMPANY_FALLBACK = ("公司", "企业", "品牌", "供应商", "服务商", "厂商")
_TABLE_COMPANY_HEADER_EXCLUDE = ("诉求", "红线", "场景", "能力", "标签", "适合", "指标", "数值", "说明", "特点")
_TABLE_RANK_HEADERS = ("排名", "序号", "位次", "rank", "no")
_TABLE_CATEGORY_LABEL_HINTS = ("梯队", "优先", "应对", "场景", "诉求", "头部人力", "驱动型", "科技驱动")


def _normalize_table_header(cell: str) -> str:
    return re.sub(r"\s+", "", _clean_item_name(cell)).casefold()


def _header_matches_company(column: str) -> bool:
    norm = _normalize_table_header(column)
    if not norm:
        return False
    if any(hint in norm for hint in _TABLE_COMPANY_HEADER_EXCLUDE):
        return False
    if any(token.casefold() in norm for token in _TABLE_COMPANY_HEADERS):
        return True
    # 2026-08-12 - 「系统/产品」「推荐品牌」等变体
    if "系统" in norm and any(x in norm for x in ("产品", "名称", "软件")):
        return True
    return any(token in norm for token in _TABLE_COMPANY_FALLBACK)


def _header_matches_rank(column: str) -> bool:
    raw = str(column or "")
    # 2026-08-12 - 「品牌名单（排名不分先后）」含「排名」勿当名次列；括号会被 clean 剥掉
    if "不分先后" in raw:
        return False
    norm = _normalize_table_header(column)
    return any(token.casefold() in norm for token in _TABLE_RANK_HEADERS)


def _table_headers_mark_unordered(header_cells: list[str]) -> bool:
    """表头声明名单无序时，格内/跨行出现序都不是推荐位次。

    2026-08-12 - _clean_item_name 会剥掉「（排名不分先后）」括号，须查原文
    """
    return any("不分先后" in str(cell or "") for cell in header_cells)


def _resolve_table_columns(header_cells: list[str]) -> tuple[int | None, int | None]:
    company_col: int | None = None
    rank_col: int | None = None
    for index, cell in enumerate(header_cells):
        if _header_matches_company(cell):
            company_col = index
        if _header_matches_rank(cell):
            rank_col = index
    if company_col is None:
        return None, None
    return company_col, rank_col


_STORE_TABLE_COL_HINTS = (
    "门店名称", "门店", "专卖店", "经销商", "店铺", "商户", "店名",
)


def _store_brand_dedup_key(name: str) -> str:
    """门店表品牌列去重键：兔宝宝/兔宝宝板材 → 同一品牌。"""
    key = _clean_item_name(str(name or ""))
    key = re.sub(r"(?:板材|木业|饰材)(?:专卖|直营)?$", "", key)
    return key.strip().casefold()


def _is_new_store_brand_row(cell: str, prev_brand: str | None) -> bool:
    """分享页缺列行首格仍是短品牌名（千年舟/大王椰）→ 新品牌行，不是续行。"""
    text = _clean_item_name(str(cell or ""))
    if not text or len(text) > 12:
        return False
    if any(h in text for h in ("专卖店", "易装馆", "经营部", "总店", "旗舰店", "定制家居", "木业")):
        return False
    if prev_brand:
        prev_key = _store_brand_dedup_key(prev_brand)
        cur_key = _store_brand_dedup_key(text)
        if prev_key and (cur_key == prev_key or prev_key in cur_key):
            return False
    if not _looks_like_company_list_name(text):
        return False
    return True


def _looks_like_store_continuation_cell(cell: str, prev_brand: str | None) -> bool:
    """分享页门店表续行：首格是店名不是新品牌（缺品牌列）。"""
    text = str(cell or "").strip()
    if not text or not prev_brand:
        return False
    prev_key = _store_brand_dedup_key(prev_brand)
    cur_key = _store_brand_dedup_key(text)
    if cur_key == prev_key:
        return True
    if prev_key and prev_key in cur_key:
        return True
    if text.startswith(str(prev_brand).replace("板材", "")):
        return True
    if any(h in text for h in ("专卖店", "易装馆", "经营部", "总店", "旗舰店", "定制家居")):
        return len(text) > max(len(prev_brand) + 2, 8)
    return False


def _is_store_list_table_header(header_cells: list[str]) -> bool:
    """「品牌|门店名称」类表：同一品牌多门店行只计品牌首次出现序。"""
    if not header_cells:
        return False
    has_brand_col = any(_header_matches_company(c) for c in header_cells)
    if not has_brand_col:
        return False
    norms = [_normalize_table_header(c) for c in header_cells]
    return any(any(h in n for h in _STORE_TABLE_COL_HINTS) for n in norms)


def _looks_like_table_category_label(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return True
    if any(hint in text for hint in _TABLE_CATEGORY_LABEL_HINTS):
        return True
    if len(text) >= 4 and (text.endswith("型") or text.endswith("类")):
        return True
    if re.fullmatch(r".*(BPO|外包)$", text) and len(text) >= 6:
        return True
    return False


def _split_table_company_cell(cell: str) -> list[str]:
    """格内并列公司拆成名单（按出现顺序）；方案 B：位次=格内第几个。"""
    raw = str(cell or "").strip()
    if not raw:
        return []

    names: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = _clean_item_name(value)
        if not cleaned or cleaned in seen:
            return
        if _looks_like_table_category_label(cleaned):
            return
        if not _looks_like_company_list_name(cleaned):
            return
        seen.add(cleaned)
        names.append(cleaned)

    # 优先：加粗公司名（表格常见 **泰盈**、**鸿联九五**）
    bolds = re.findall(r"\*\*([^*]+)\*\*", raw)
    if bolds:
        for item in bolds:
            add(item)
        if names:
            return names

    # （如A、B）/ （例如A、B）
    like = re.search(r"[（(](?:如|例如|比如)?([^）)]+)[)）]", raw)
    if like:
        for part in re.split(r"[、，,/]", like.group(1)):
            add(part)
        if names:
            return names

    # 去括号说明后按顿号拆
    stripped = re.sub(r"[（(][^）)]*[)）]", "", raw)
    if any(sep in stripped for sep in ("、", "，", ",")):
        for part in re.split(r"[、，,]", stripped):
            add(part)
        if names:
            return names

    add(raw)
    return names


def _parse_markdown_table_block(
    lines: list[str],
    append_item: Callable[..., None],
    category: str | None,
) -> bool:
    """Parse company rows from a markdown table; multi-name cells rank by in-cell order."""
    parsed_lines = [
        line.strip()
        for line in lines
        if line.strip() and not _is_table_separator_row(line)
    ]
    if len(parsed_lines) < 2:
        return False
    header_cells = _split_markdown_table_cells(parsed_lines[0])
    company_col, rank_col = _resolve_table_columns(header_cells)
    if company_col is None:
        return False
    # 2026-08-12 - 「排名不分先后」多源名单勿摊成结构化名次（派雅被抬到10/25）
    if _table_headers_mark_unordered(header_cells):
        return True
    # 2026-08-26 - 门店题「品牌|门店名称」多行同品牌勿按门店行累加（南昌大王椰第9→第3）
    store_mode = _is_store_list_table_header(header_cells)
    brand_seen: dict[str, int] = {}
    row_rank = 0
    parsed_any = False
    for row in parsed_lines[1:]:
        cells = _split_markdown_table_cells(row)
        if company_col >= len(cells):
            continue
        names = _split_table_company_cell(cells[company_col])
        if not names:
            continue
        explicit_rank = None
        if rank_col is not None and rank_col < len(cells):
            explicit_rank = _parse_rank_token(cells[rank_col])
        if store_mode:
            for name in names:
                key = _store_brand_dedup_key(name)
                if not key or key in brand_seen:
                    continue
                brand_seen[key] = len(brand_seen) + 1
                append_item(
                    name,
                    explicit_rank if explicit_rank is not None else brand_seen[key],
                    category=category,
                )
                parsed_any = True
            continue
        if len(names) == 1:
            row_rank += 1
            append_item(
                names[0],
                explicit_rank if explicit_rank is not None else row_rank,
                category=category,
            )
            parsed_any = True
            continue
        # 方案 B：格内并列按出现顺序记 1..n（展示仍是普通名次）
        for index, name in enumerate(names, 1):
            append_item(name, index, category=category)
            parsed_any = True
        row_rank += 1
    return parsed_any


def _split_tsv_cells(line: str) -> list[str]:
    return [cell.strip() for cell in str(line or "").split("\t")]


def _is_tsv_table_header_line(line: str) -> bool:
    """分享页制表符表头：品牌名称\\t核心特点\\t…

    2026-08-12 - 数据行「…领导品牌」含「品牌」勿当表头，否则公司列偏到描述列
    """
    if "\t" not in (line or ""):
        return False
    cells = _split_tsv_cells(line)
    if len(cells) < 2:
        return False
    first = _clean_item_name(cells[0])
    # 2026-08-26 - 分享页表内「-\t品牌门店/特点」续行脚注勿当新表头，否则截断大王椰
    if not first or first in {"-", "—", "–", "·"}:
        return False
    company_col, _rank_col = _resolve_table_columns(cells)
    if company_col is None:
        return False
    header_cell = cells[company_col]
    norm = _normalize_table_header(header_cell)
    if not norm or len(norm) > 12:
        return False
    # 首列已是具体品牌名，且「品牌」命中在其它列 → 数据行
    first = _clean_item_name(cells[0])
    if (
        first
        and _looks_like_company_list_name(first)
        and company_col != 0
        and not any(token.casefold() in _normalize_table_header(cells[0]) for token in _TABLE_COMPANY_HEADERS)
        and _normalize_table_header(cells[0]) not in {"品牌", "企业", "公司", "厂商"}
    ):
        return False
    if any(token.casefold() in norm for token in _TABLE_COMPANY_HEADERS):
        return True
    if norm in {"品牌", "企业", "公司", "厂商", "机构"}:
        return True
    return False


def _is_tsv_table_noise_line(line: str) -> bool:
    """分享页表格被拆开的荣誉/脚注行，不当选手、也不结束表。"""
    text = str(line or "").strip()
    if not text:
        return True
    if "\t" in text:
        return False
    if text in {"-", "—", "–"}:
        return True
    if text.isdigit():
        return True
    if text.startswith(("、", "，", ",")):
        return True
    if re.match(r"^20\d{2}年", text) and len(text) <= 40:
        return True
    return False


def _is_tsv_broken_continuation_row(cells: list[str]) -> bool:
    """引用掐断后「。\\t银行、政府…」续行：首格不是场景/品牌，勿当新选手行。

    2026-09-03 - 场景×推荐 TSV 被 -\\nN 拆行后，适用客户列挤进 company_col
    """
    if not cells:
        return True
    first = str(cells[0] or "").strip()
    if not first or first in {".", "。", "，", ",", "-", "—", "–", "·"}:
        return True
    if first.startswith(("。", "，", ",", ".")):
        return True
    return False


def _tsv_row_company_names(line: str, company_col: int) -> list[str]:
    cells = _split_tsv_cells(line)
    if company_col >= len(cells):
        return []
    if _is_tsv_broken_continuation_row(cells):
        return []
    names = _split_table_company_cell(cells[company_col])
    # 表头噪声（偶发被当成数据行）
    skip = {
        _normalize_table_header(h)
        for h in (*_TABLE_COMPANY_HEADERS, "品牌", "企业", "公司")
    }
    return [
        name
        for name in names
        if _normalize_table_header(name) not in skip and not _looks_like_table_category_label(name)
    ]


def _scene_subsection_key(line: str) -> str | None:
    """需求场景子段（单城市/多城市/候车亭）— 只作计位锚点，不当公司。"""
    text = str(line or "").strip()
    # 2026-08-24 - 公司 bullet 描述含「候车亭起家」误触 shelter，吞掉白马户外等首条
    if BULLET_ITEM_RE.match(text) and re.search(r"\*\*[^*]+\*\*[：:]", text):
        return None
    if re.search(r"多城市全国统投|多城.{0,6}统投", text):
        return "multi_city"
    if "单城市深耕" in text:
        return "single_city"
    if re.search(r"候车亭\s*/\s*灯箱", text) or re.search(r"候车亭.{0,4}灯箱", text):
        return "shelter"
    return None


def _extract_bullet_brand_candidates(line: str) -> list[str]:
    """并列 bullet：**A、B、C等** / 整合代理：如A、B、C等。

    2026-08-24 - 地铁/机场/公交元宝粘行并列组，档内位次=该 bullet 序号
    """
    raw = re.sub(r"^[-•·▪*]\s*", "", str(line or "").strip())
    names: list[str] = []

    def collect(parts: list[str]) -> list[str]:
        out: list[str] = []
        for part in parts:
            cleaned = _clean_item_name(re.sub(r"等$", "", part.strip()))
            if cleaned and _looks_like_company_list_name(cleaned):
                out.append(cleaned)
        return out

    bold_match = re.match(r"^\*\*([^*]+)\*\*(?:[：:]|$)", raw)
    if bold_match:
        head = re.sub(r"等$", "", bold_match.group(1).strip())
        if re.search(r"[、，,]", head):
            names = collect(re.split(r"[、，,]", head))
            if len(names) >= 2:
                return names

    if _ROLE_LABEL_BULLET_RE.match(raw) or re.search(r"[：:]\s*如", raw):
        like_match = re.search(r"如\s*([^。；\n]+)", raw)
        if like_match:
            chunk = like_match.group(1).strip()
            chunk = re.split(r"等", chunk, maxsplit=1)[0]
            chunk = re.sub(r"[（(][^）)]*[)）]", "", chunk)
            chunk = re.sub(r"\*\*([^*]+)\*\*", r"\1", chunk)
            if re.search(r"[、，,]", chunk):
                names = collect(re.split(r"[、，,]", chunk))
                if names:
                    return names
    return []


def _split_combined_header_brands(text: str) -> list[str]:
    """### 艾迪亚控股、澜翼传媒、麦迪威广告 → 多个品牌名（同段并列排名）。"""
    cleaned = re.sub(r"^#+\s*", "", (text or "").strip())
    cleaned = re.sub(r"\[citation:\d+\]", "", cleaned, flags=re.I).strip()
    # 2026-08-24 - ｜后是卖点；冒号后描述里的中文逗号不是品牌顿号
    cleaned = re.split(r"[｜|]", cleaned, maxsplit=1)[0].strip()
    if "：" in cleaned or ":" in cleaned:
        return []
    cleaned = re.sub(r"^(?:[一二三四五六七八九十百]+|\d+)\s*[、.．)）]\s*", "", cleaned).strip()
    if not cleaned or "、" not in cleaned:
        return []
    # 一、行业双寡头 这类章节标题不要拆成多个品牌
    if SECTION_TITLE_RE.match(cleaned):
        return []
    if _looks_like_subcategory_header(cleaned):
        return []
    head = re.sub(r"[（(][^）)]*[)）]", "", cleaned).strip()
    if "、" not in head:
        return []
    parts = re.split(r"[、]", head)
    names = [_clean_item_name(part.strip()) for part in parts if part.strip()]
    names = [name for name in names if name and _looks_like_company_list_name(name)]
    if len(names) < 2:
        return []
    if any(len(name) > 36 for name in names):
        return []
    return names


def _strip_category_prefix(text: str) -> str:
    return re.sub(r"^[一二三四五六七八九十百]+[、.．]\s*", "", text.strip()).strip()


def _parse_markdown_header(line: str) -> tuple[int, str] | None:
    match = MARKDOWN_HEADER_RE.match(line.strip())
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _is_subsection_label(content: str) -> bool:
    cleaned = re.sub(r"^[一二三四五六七八九十\d]+[\.、．]\s*", "", content).strip()
    cleaned = re.sub(r"^\*\*|\*\*$", "", cleaned).strip()
    head = cleaned.split("：", 1)[0].split(":", 1)[0].strip()
    head = re.sub(r"^\*\*|\*\*$", "", head).strip()
    if head in SUBSECTION_LABELS or cleaned in SUBSECTION_LABELS:
        return True
    if _FIELD_LABEL_RE.match(head) or _FIELD_LABEL_RE.match(cleaned):
        return True
    return any(cleaned.startswith(label) for label in SUBSECTION_LABELS)


def _looks_like_subcategory_header(content: str) -> bool:
    """### 区域优质工程商 / 🥇 一线… → 子分类标题，不是公司名。"""
    cleaned = re.sub(r"^[#\s\d\.、]+", "", (content or "").strip())
    cleaned = re.sub(r"\[citation:\d+\]", "", cleaned, flags=re.I).strip()
    # 2026-08-24 - 先剥括号说明，避免「福庆板材（江苏本土品牌）」因「本土」误判子类
    cleaned = re.sub(r"[（(][^）)]*[)）]", "", cleaned).strip()
    if not cleaned or NUMBERED_TITLE_RE.match(cleaned):
        return False
    if _TIER_MEDAL_RE.match(cleaned):
        return True
    cleaned = _TIER_MEDAL_RE.sub("", cleaned).strip()
    # 剥 emoji 前缀（🌍🏛️🇨🇳）
    cleaned = re.sub(r"^[\U0001F300-\U0001F9FF\u2600-\u27BF]+\s*", "", cleaned).strip()
    # 「章管家——物理印控 / 高性价比」卖点里的性价比不是子类
    cleaned = re.split(r"[—–―]{2,}", cleaned, maxsplit=1)[0].strip()
    if SECTION_TITLE_RE.match(cleaned):
        return True
    # 像「### 福庆板材」品牌授权标题不是子类；「区域优质工程商/头部上市大厂」仍是子类
    brand_probe = _clean_item_name(cleaned)
    if (
        brand_probe
        and re.search(r"(板材|涂料|传媒|广告|光电|科技|家居)$", brand_probe)
        and _looks_like_company_list_name(brand_probe)
        and not any(hint in brand_probe for hint in ("一线", "二线", "三线", "梯队", "榜单", "巨头"))
    ):
        return False
    return any(hint in cleaned for hint in _SUBCATEGORY_HINTS)


def _next_section_rank(counters: dict[str | None, int], section: str | None) -> int:
    counters[section] = counters.get(section, 0) + 1
    return counters[section]


def _is_category_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return False
    if LIST_ITEM_RE.match(stripped) or BULLET_ITEM_RE.match(stripped):
        return False
    header = _parse_markdown_header(stripped)
    if header:
        level, content = header
        if NUMBERED_TITLE_RE.match(content):
            return False
        if level >= 3 and not _is_subsection_label(content) and not SECTION_TITLE_RE.match(content):
            return False
        if level == 1:
            return False
        return True
    if re.match(r"^\*\*.+\*\*$", stripped):
        return True
    if re.match(r"^【.+】$", stripped):
        return True
    if re.match(r"^(?:分类|类别|类型|场景)[一二三四五六七八九十\d]+[：:]", stripped):
        return True
    if SECTION_TITLE_RE.match(stripped):
        content = re.sub(r"^[一二三四五六七八九十百]+[、.．]\s*", "", stripped)
        return len(content) <= 40 and not content.endswith("。")
    # 2026-08-12 - 分享页「主流门窗品牌榜单概览 / 实力品牌速览」无 # 也要当段
    if re.search(r"(?:榜单概览|品牌速览|实力品牌速览|主流门窗品牌)", stripped) and len(stripped) <= 60:
        return True
    return False


def _extract_category_name(line: str) -> str:
    stripped = line.strip()
    for pattern in (
        r"^#{1,4}\s*(.+)$",
        r"^\*\*(.+?)\*\*$",
        r"^【(.+?)】$",
        r"^[一二三四五六七八九十百]+[、.．]\s*(.+)$",
        r"^(?:分类|类别|类型|场景)[一二三四五六七八九十\d]+[：:]\s*(.+)$",
    ):
        match = re.match(pattern, stripped)
        if match:
            return _strip_category_prefix(_clean_item_name(match.group(1)))
    return _strip_category_prefix(_clean_item_name(stripped))


def ranking_entry_category(entry: dict[str, Any]) -> str | None:
    for key in ("category", "group", "type", "section", "categoryName", "category_name"):
        value = entry.get(key)
        if value:
            return str(value).strip()
    return None


def ranking_entry_name(entry: dict[str, Any]) -> str:
    raw = str(
        entry.get("name")
        or entry.get("brandName")
        or entry.get("brand")
        or entry.get("keyword")
        or "",
    ).strip()
    return sanitize_entity_name(raw)


def ranking_entry_explicit_rank(entry: dict[str, Any]) -> int | float | None:
    for key in ("rank", "position", "rankNo", "mentionPosition"):
        value = entry.get(key)
        if value is None:
            continue
        coerced = _coerce_rank_number(value)
        if coerced is not None:
            return coerced
    return None


def normalize_structured_rankings(raw_entries: list[Any] | None) -> list[dict[str, Any]]:
    """Normalize API ranking JSON；有 category 时按段内出场序重排，忽略跨段连号。"""
    results: list[dict[str, Any]] = []
    appearance_counters: dict[str | None, int] = {}
    for raw in raw_entries or []:
        if not isinstance(raw, dict):
            continue
        name = _clean_item_name(ranking_entry_name(raw)) or ranking_entry_name(raw)
        if not name:
            continue
        # API/旧缓存也会把「核心优势」当成选手；与正文解析同一门禁
        if _is_subsection_label(name) or name in SUBSECTION_LABELS:
            continue
        if name in _NON_COMPANY_TOKENS:
            continue
        if not _looks_like_company_list_name(name):
            continue
        category = ranking_entry_category(raw)
        if category:
            appearance_counters[category] = appearance_counters.get(category, 0) + 1
            rank_value: int | float = appearance_counters[category]
        else:
            rank_value_opt = ranking_entry_explicit_rank(raw)
            if rank_value_opt is None:
                appearance_counters[None] = appearance_counters.get(None, 0) + 1
                rank_value = appearance_counters[None]
            else:
                rank_value = rank_value_opt
                numeric = _coerce_rank_number(rank_value)
                if numeric is not None:
                    appearance_counters[None] = max(appearance_counters.get(None, 0), int(numeric))
        results.append({"name": name, "rank": rank_value, "category": category})

    # ponytail: 模力 allRankings 常整表 rank=1；无分段且同位次扎堆时按出场序重排
    unscoped = [row for row in results if not row.get("category")]
    if not unscoped:
        return results
    if len(unscoped) >= 2:
        numeric_ranks: list[float] = []
        for row in unscoped:
            coerced = _coerce_rank_number(row.get("rank"))
            if coerced is not None:
                numeric_ranks.append(float(coerced))
        if len(numeric_ranks) == len(unscoped) and len(set(numeric_ranks)) == 1:
            for index, row in enumerate(unscoped, start=1):
                row["rank"] = index
            return results
    # 2026-09-03 - 滤掉引用数字后显式位次留空洞（只剩品牌仍标2）→ 按过滤后出场序重排
    expected = set(range(1, len(unscoped) + 1))
    actual: set[int] = set()
    contiguous = True
    for row in unscoped:
        coerced = _coerce_rank_number(row.get("rank"))
        if coerced is None or float(coerced) != int(coerced):
            contiguous = False
            break
        actual.add(int(coerced))
    if not contiguous or actual != expected:
        for index, row in enumerate(unscoped, start=1):
            row["rank"] = index
    return results


def rankings_for_storage(
    answer: str | None,
    remote_rankings: list[Any] | None = None,
) -> list[dict[str, Any]] | None:
    """入库榜单：正文能分段则写段内序+category；否则规范化远端扁平榜。

    2026-07-27 - 模力 allRankings 跨段连号与段内名次冲突 - 持久化以正文分段为准
    """
    parsed = parse_answer_rankings(answer or "")
    if parsed:
        return [
            {
                "name": row.get("name"),
                "rank": row.get("rank"),
                "category": row.get("category"),
            }
            for row in parsed
            if row.get("name")
        ]
    remote_norm = normalize_structured_rankings(remote_rankings or [])
    return remote_norm or None


def parse_answer_rankings(text: str) -> list[dict[str, Any]]:
    """Extract ranked list items from answer text, grouped by category when present."""
    if not text:
        return []

    normalized = _normalize_answer_layout(text)

    results: list[dict[str, Any]] = []
    current_category: str | None = None
    current_section: str | None = None
    appearance_counters: dict[str | None, int] = {}
    scene_subsection: str | None = None
    scene_counters: dict[str, int] = {}
    in_company_block = False
    company_from_heading = False

    def append_item(name: str, rank: int | None, *, category: str | None = None) -> None:
        cleaned = _extract_list_item_name(name)
        if not cleaned or not _looks_like_company_list_name(cleaned):
            return
        # 公司块下的「核心优势/服务能力」不是选手
        if _is_subsection_label(cleaned) or cleaned in SUBSECTION_LABELS:
            return
        if cleaned in _NON_COMPANY_TOKENS:
            return
        # 2026-08-24 - 授权门店清单里的「xx整家店」不当品牌
        if _looks_like_store_list_name(cleaned):
            return
        # 2026-08-24 - 区县/市场标题不当选手（门店推荐里常见）
        if _looks_like_geo_place_label(cleaned):
            return
        if _SCENE_SUBSECTION_RE.search(cleaned) or cleaned in {"区域型", "整合代理"}:
            return
        bucket = category if category is not None else (current_section or current_category)
        # 2026-08-24 - 「选择建议」表按推荐列计位；散文贴士仍跳过
        if _is_non_rank_category(bucket) and not (
            rank is not None and "选择建议" in str(bucket or "")
        ):
            return
        if rank is None:
            appearance_counters[bucket] = appearance_counters.get(bucket, 0) + 1
            rank = appearance_counters[bucket]
        else:
            appearance_counters[bucket] = max(appearance_counters.get(bucket, 0), rank)
        results.append({"name": cleaned, "rank": rank, "category": bucket})

    table_buffer: list[str] = []
    # 2026-08-12 - DeepSeek 分享页制表符品牌表（非 markdown |）也要进结构化榜
    tsv_mode = False
    tsv_company_col = 0
    tsv_store_mode = False
    tsv_brand_seen: dict[str, int] = {}
    tsv_prev_brand: str | None = None
    tsv_header_cols = 0

    def flush_table_buffer() -> None:
        nonlocal table_buffer
        if not table_buffer:
            return
        _parse_markdown_table_block(
            table_buffer,
            append_item,
            current_section or current_category,
        )
        table_buffer = []

    def end_tsv_mode() -> None:
        nonlocal tsv_mode, tsv_company_col, tsv_store_mode, tsv_brand_seen, tsv_prev_brand, tsv_header_cols
        tsv_mode = False
        tsv_company_col = 0
        tsv_store_mode = False
        tsv_brand_seen = {}
        tsv_prev_brand = None
        tsv_header_cols = 0

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            flush_table_buffer()
            # 分享页表行间常插空行/荣誉碎行，保持 tsv_mode
            continue
        if _is_markdown_table_line(line):
            end_tsv_mode()
            table_buffer.append(line)
            continue
        flush_table_buffer()

        # 已在 TSV 表内：先当数据行，避免描述含「品牌」被误判为新表头
        if tsv_mode and "\t" in line:
            names = _tsv_row_company_names(line, tsv_company_col)
            if names:
                if tsv_store_mode:
                    raw_name = names[0]
                    cells = _split_tsv_cells(line)
                    is_new_brand = _is_new_store_brand_row(raw_name, tsv_prev_brand)
                    if (
                        tsv_prev_brand
                        and not is_new_brand
                        and (
                            _looks_like_store_continuation_cell(raw_name, tsv_prev_brand)
                            or (tsv_header_cols and len(cells) < tsv_header_cols - 1)
                        )
                    ):
                        brand_name = tsv_prev_brand
                    else:
                        brand_name = raw_name
                        tsv_prev_brand = brand_name
                    key = _store_brand_dedup_key(brand_name)
                    if not key or key in tsv_brand_seen:
                        continue
                    tsv_brand_seen[key] = len(tsv_brand_seen) + 1
                    append_item(
                        brand_name,
                        tsv_brand_seen[key],
                        category=current_section or current_category,
                    )
                else:
                    for name in names:
                        append_item(name, None, category=current_section or current_category)
                continue
            # 2026-08-26 - 「-\t品牌门店」等脚注行有 tab 但无公司名，勿落出 tsv_mode
            if _is_tsv_table_noise_line(line) or re.match(r"^-\s*\t", line):
                continue

        if _is_tsv_table_header_line(line):
            cells = _split_tsv_cells(line)
            company_col, _rank_col = _resolve_table_columns(cells)
            if company_col is not None:
                tsv_mode = True
                tsv_company_col = company_col
                tsv_store_mode = _is_store_list_table_header(cells)
                tsv_brand_seen = {}
                tsv_prev_brand = None
                tsv_header_cols = len(cells)
            continue

        if tsv_mode:
            if _is_tsv_table_noise_line(line):
                continue
            # 非制表符：新段标题则结束表；短碎行跳过；长散文结束表后落入后续逻辑
            header = _parse_markdown_header(line)
            if header or _is_category_header(line) or LIST_ITEM_RE.match(line):
                end_tsv_mode()
            elif len(line) <= 40:
                continue
            else:
                end_tsv_mode()

        header = _parse_markdown_header(line)
        if header:
            end_tsv_mode()
            level, content = header
            content = re.sub(r"\[citation:\d+\]", "", content, flags=re.I).strip()
            numbered_company = _company_from_numbered_heading(content)
            if numbered_company:
                # ### 一、广州伟源光电科技有限公司（…）→ 选手，不是分类
                append_item(numbered_company, None)
                in_company_block = True
                company_from_heading = True
                continue
            # 2026-08-24 - ### 7）大王椰｜生态板 / ### 7.大王椰 → 父级 ## 段内计位
            if level >= 3:
                pipe_nominees = _nominees_from_pipe_numbered_heading(content)
                if pipe_nominees:
                    shared_rank = _next_section_rank(appearance_counters, current_section)
                    for name in pipe_nominees:
                        append_item(name, shared_rank, category=current_section or current_category)
                    in_company_block = True
                    company_from_heading = True
                    continue
            numbered = NUMBERED_TITLE_RE.match(content)
            if numbered:
                body = numbered.group(2).strip()
                brand_side = re.split(r"[｜|]", body, maxsplit=1)[0].strip()
                # 2026-08-18 - ### 3. 中国本土市场活跃榜单 不是公司；当选手还会挡住后面 - **鸿联九五**
                # 2026-08-24 - 「千年舟｜高性价比一线」品牌侧不是子类，勿整行当段名
                if _is_non_rank_category(brand_side) or _looks_like_subcategory_header(brand_side):
                    cat = _extract_category_name(body) or body
                    current_section = cat
                    current_category = cat
                    appearance_counters.setdefault(current_section, 0)
                    in_company_block = False
                    company_from_heading = False
                    continue
                append_item(brand_side, _next_section_rank(appearance_counters, current_section))
                in_company_block = True
                company_from_heading = True
                continue
            if level == 1:
                # `# 怎么选公司？` 不能直接跳过：否则 1~7 对照表仍挂在上一 ## 节，rank 被吃成 7
                cat = _extract_category_name(line)
                if _is_non_rank_category(cat):
                    current_section = cat
                    current_category = cat
                    appearance_counters.setdefault(current_section, 0)
                    in_company_block = False
                company_from_heading = False
                continue
            if level == 2 or SECTION_TITLE_RE.match(content):
                current_section = _extract_category_name(line)
                current_category = current_section
                appearance_counters.setdefault(current_section, 0)
                scene_subsection = None
                scene_counters.clear()
                in_company_block = False
                company_from_heading = False
                continue
            if level == 3 and _looks_like_subcategory_header(content):
                current_section = _extract_category_name(line)
                current_category = current_section
                appearance_counters.setdefault(current_section, 0)
                in_company_block = False
                company_from_heading = False
                continue
            combined = _split_combined_header_brands(content)
            if combined:
                for index, name in enumerate(combined, 1):
                    append_item(name, index, category=current_section or current_category)
                in_company_block = True
                company_from_heading = True
                continue
            if _is_subsection_label(content):
                # 选择建议 / 补充推荐：结束公司详情块，不当选手
                in_company_block = False
                company_from_heading = False
                if _is_non_rank_category(content) or content in SUBSECTION_LABELS:
                    current_section = _extract_category_name(line)
                    current_category = current_section
                continue
            # H3 不像公司名（梯队/描述标题）→ 当段重置，避免吞掉后续 bullet
            # ponytail: 旧逻辑一律 append_item，🥇一线 会被当成选手且 in_company_block 丢掉公司列表
            if level >= 3 and not _looks_like_company_list_name(
                _clean_item_name(_TIER_MEDAL_RE.sub("", content))
            ):
                current_section = _extract_category_name(line)
                current_category = current_section
                appearance_counters.setdefault(current_section, 0)
                in_company_block = False
                company_from_heading = False
                continue
            if _looks_like_geo_place_label(_clean_item_name(content)):
                current_section = _extract_category_name(line)
                current_category = current_section
                appearance_counters[current_section] = 0
                in_company_block = False
                company_from_heading = False
                continue
            append_item(content, _next_section_rank(appearance_counters, current_section))
            in_company_block = True
            company_from_heading = True
            continue

        if _is_category_header(line):
            end_tsv_mode()
            stripped = re.sub(r"^\*\*|\*\*$", "", line.strip())
            stripped = re.sub(r"^【|】$", "", stripped).strip()
            numbered_company = _company_from_numbered_heading(stripped)
            if numbered_company:
                append_item(numbered_company, None)
                in_company_block = True
                company_from_heading = True
                continue
            category_name = _extract_category_name(line)
            combined = _split_combined_header_brands(category_name)
            if combined:
                for index, name in enumerate(combined, 1):
                    append_item(name, index, category=current_section or current_category)
                in_company_block = True
                company_from_heading = True
                continue
            current_section = category_name
            current_category = category_name
            appearance_counters.setdefault(current_category, 0)
            in_company_block = False
            company_from_heading = False
            continue

        if in_company_block:
            # 2026-08-24 - 整合代理：如A、B、C 仍在公司块内，须放行给并列 bullet 分支
            if _extract_bullet_brand_candidates(line):
                in_company_block = False
                company_from_heading = False
            else:
                peer = LIST_ITEM_RE.match(line)
                if peer:
                    append_item(peer.group(4), None)
                    in_company_block = True
                    company_from_heading = False
                    continue
                # 详情字段跳过. 标题开出的公司卡里, 没有公司名的能力条目不是下一选手.
                bullet_match = BULLET_ITEM_RE.match(line)
                if bullet_match and re.search(r"\*\*[^*]+\*\*", line):
                    body = bullet_match.group(1) or bullet_match.group(2) or ""
                    name = _extract_list_item_name(body)
                    peer_ok = _is_peer_company_bullet(name, body)
                    if company_from_heading and not _has_company_entity_signal(name):
                        peer_ok = False
                    if peer_ok:
                        in_company_block = False
                        company_from_heading = False
                    else:
                        continue
                else:
                    continue

        scene_key = _scene_subsection_key(line)
        if scene_key:
            scene_subsection = scene_key
            scene_counters[scene_key] = 0
            in_company_block = False
            company_from_heading = False
            continue

        combo_brands = _extract_bullet_brand_candidates(line)
        if combo_brands:
            bucket = current_section or current_category
            if scene_subsection:
                scene_counters[scene_subsection] = scene_counters.get(scene_subsection, 0) + 1
                bullet_rank = scene_counters[scene_subsection]
            else:
                appearance_counters[bucket] = appearance_counters.get(bucket, 0) + 1
                bullet_rank = appearance_counters[bucket]
            for brand in combo_brands:
                cleaned = _clean_item_name(brand)
                if cleaned and _looks_like_company_list_name(cleaned):
                    results.append({"name": cleaned, "rank": bullet_rank, "category": bucket})
            in_company_block = True
            company_from_heading = False
            continue

        if _ROLE_LABEL_BULLET_RE.match(re.sub(r"^[-•·▪*]\s*", "", line)):
            bucket = current_section or current_category
            # 2026-08-24 - 区域型/整合代理 仅作标签行；有「如A、B」时已在 combo_brands 分支处理
            if not re.search(r"[：:]\s*如", line):
                appearance_counters[bucket] = appearance_counters.get(bucket, 0) + 1
            in_company_block = False
            company_from_heading = False
            continue

        match = LIST_ITEM_RE.match(line)
        if match:
            # 分段重排：段内按出场序计位；编号公司后进入详情块，忽略核心优势等 bullet
            before = len(results)
            if scene_subsection:
                scene_counters[scene_subsection] = scene_counters.get(scene_subsection, 0) + 1
                append_item(match.group(4), scene_counters[scene_subsection], category=current_section or current_category)
            else:
                append_item(match.group(4), None)
            if len(results) > before:
                in_company_block = True
                company_from_heading = False
            continue

        bullet = BULLET_ITEM_RE.match(line)
        if bullet:
            body = bullet.group(1) or bullet.group(2) or ""
            if scene_subsection:
                scene_counters[scene_subsection] = scene_counters.get(scene_subsection, 0) + 1
                append_item(body, scene_counters[scene_subsection], category=current_section or current_category)
            else:
                append_item(body, None)
            continue

    flush_table_buffer()
    end_tsv_mode()

    if not results:
        for match in PROSE_RANK_RE.finditer(normalized):
            rank = _parse_rank_token(match.group(1))
            append_item(match.group(2), rank)

    return results


_SCOPE_NOISE_RE = re.compile(r"推荐|哪家好|哪个|怎么选|怎么样|排行|榜单|有哪些|是什么")
_MAJOR_SECTION_RE = re.compile(r"^[一二三四五六七八九十百]+[、.．]\s*\S")


def _scope_match_tokens(scope: str) -> list[str]:
    cleaned = _SCOPE_NOISE_RE.sub(" ", str(scope or ""))
    tokens: list[str] = []
    for match in re.finditer(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{2,}", cleaned):
        token = match.group(0).strip()
        if token and token not in tokens:
            tokens.append(token)
        # 机场广告公司 → 再切 机场/广告/公司，避免整词拼不上分段标题
        if len(token) >= 4 and re.fullmatch(r"[\u4e00-\u9fff]+", token):
            for size in (2, 3):
                for index in range(0, len(token) - size + 1):
                    piece = token[index:index + size]
                    if piece not in tokens:
                        tokens.append(piece)
    return tokens


_SCOPE_GENERIC_TOKENS = frozenset({
    "公司", "企业", "厂商", "品牌", "外包", "服务商", "推荐", "哪家", "哪个",
    "平台", "机构", "厂家",
})


def _text_overlap_score(left: str, right: str) -> int:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return -1
    if left_text == right_text:
        return 2000 + len(left_text)
    if left_text in right_text:
        return 1500 + len(left_text)
    if right_text in left_text:
        return 1400 + len(right_text)
    prefix = 0
    for left_char, right_char in zip(left_text, right_text):
        if left_char != right_char:
            break
        prefix += 1
    if prefix >= 4:
        return 500 + prefix
    left_fold = left_text.casefold()
    score = 0
    for token in _scope_match_tokens(right_text):
        if token.casefold() not in left_fold:
            continue
        # 泛词（公司/外包）易把「国际知名…」「关键考量」打到同分，降权
        if token in _SCOPE_GENERIC_TOKENS:
            score += 20 + min(len(token), 2)
        else:
            score += 100 + len(token)
    return score


def _scene_alignment_bonus(category: str, scope: str) -> int:
    category_text = str(category or "").casefold()
    scope_text = str(scope or "").casefold()
    bonus = 0
    media_scope = any(token in scope_text for token in ("广告", "传媒", "媒体", "大屏", "户外", "机场", "电梯"))
    factory_scope = any(token in scope_text for token in ("显示屏", "生产", "工程", "厂家", "厂商"))
    bpo_scope = any(token in scope_text for token in ("呼叫中心", "外包", "客服", "bpo"))
    if media_scope and any(
        token in category_text
        for token in ("传媒", "媒体", "运营商", "广告", "户外", "大屏", "代理", "平台", "整合", "机场", "梯媒")
    ):
        bonus += 250
    if factory_scope and any(token in category_text for token in ("显示屏", "生产", "工程", "厂家", "厂商")):
        bonus += 250
    if media_scope and any(token in category_text for token in ("显示屏", "生产", "工程", "厂家", "厂商")):
        bonus -= 120
    if factory_scope and any(token in category_text for token in ("传媒", "媒体", "运营商", "户外")):
        bonus -= 120
    # 呼叫/外包类问题：本土/国内/性价比段优先于纯「云呼叫」产品段或选型 checklist
    if bpo_scope and any(token in category_text for token in ("本土", "中国", "国内", "亚太", "性价比", "外包商")):
        bonus += 280
    if bpo_scope and any(token in category_text for token in ("云呼叫", "技术驱动", "saas")):
        bonus -= 80
    # 2026-08-31 - 方案C：进口/国产标题互斥，避免跨段被当成同一 scope 累加
    import_cat = "进口" in category_text
    domestic_cat = "国产" in category_text or "国内" in category_text
    import_scope = "进口" in scope_text
    domestic_scope = "国产" in scope_text or "国内" in scope_text
    if import_scope and domestic_cat:
        bonus -= 400
    if domestic_scope and import_cat:
        bonus -= 400
    return bonus


def ranking_category_scope_score(category: str | None, scope: str) -> int:
    """Score how well a parsed category matches monitor keyword / prompt."""
    category_text = str(category or "").strip()
    scope_text = str(scope or "").strip()
    if not category_text or not scope_text:
        return -1
    direct = _text_overlap_score(category_text, scope_text)
    reverse = _text_overlap_score(scope_text, category_text)
    base = max(direct, reverse)
    bonus = _scene_alignment_bonus(category_text, scope_text)
    return base + bonus if base >= 0 else bonus


def _entries_in_scope(entries: list[dict[str, Any]], scope: str) -> tuple[list[dict[str, Any]], bool]:
    """Return entries whose category best matches scope; scoped=True when filter applied."""
    scope_text = str(scope or "").strip()
    if not scope_text:
        return entries, False
    categories = {str(entry.get("category") or "").strip() for entry in entries}
    categories.discard("")
    if not categories:
        return entries, False
    scores = {category: ranking_category_scope_score(category, scope_text) for category in categories}
    best = max(scores.values(), default=-1)
    if best < 100:
        return entries, False
    threshold = max(best * 0.45, 100)
    allowed = {category for category, score in scores.items() if score >= threshold}
    scoped = [entry for entry in entries if str(entry.get("category") or "").strip() in allowed]
    return scoped or entries, True


def _numeric_rank(entry: dict[str, Any]) -> float | None:
    rank = entry.get("rank")
    if rank is None:
        return None
    try:
        return float(rank)
    except (TypeError, ValueError):
        return None


def _pick_best_rank_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """业务口径：多命中取名次最靠前（数字最小）的那条。"""
    best: dict[str, Any] | None = None
    best_rank: float | None = None
    for entry in entries:
        numeric = _numeric_rank(entry)
        if numeric is None:
            continue
        if best_rank is None or numeric < best_rank:
            best = entry
            best_rank = numeric
    return best


def find_best_brand_hit_scoped(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    scope: str,
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> tuple[int | float | None, bool, dict[str, Any] | None]:
    """一次扫描：返回 (rank, matched, winning_entry)。"""
    matched_entries: list[dict[str, Any]] = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name or not match_name(name):
            continue
        if skip_name and skip_name(name):
            continue
        if _is_non_rank_category(entry.get("category")):
            continue
        matched_entries.append(entry)
    if not matched_entries:
        return None, False, None

    scoped_entries, scoped = _entries_in_scope(matched_entries, scope)
    ranked_pool = scoped_entries if scoped else matched_entries

    categorized = [
        entry for entry in ranked_pool
        if str(entry.get("category") or "").strip()
    ]
    winner = _pick_best_rank_entry(categorized or ranked_pool)
    if winner is None:
        return None, True, None
    try:
        target = float(winner["rank"])
    except (TypeError, ValueError):
        return None, True, winner

    hits = [
        entry for entry in ranked_pool
        if (numeric := _numeric_rank(entry)) is not None and float(numeric) == target
    ]
    if not hits:
        return target, True, winner
    scope_text = str(scope or "").strip()
    if scope_text and len(hits) > 1:
        hits_sorted = sorted(
            hits,
            key=lambda item: ranking_category_scope_score(
                str(item.get("category") or "").strip(),
                scope_text,
            ),
            reverse=True,
        )
        return target, True, hits_sorted[0]
    return target, True, hits[0]


def find_best_brand_rank_scoped(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    scope: str,
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> tuple[int | float | None, bool]:
    """分段名次：多命中时优先取问题场景匹配的分段，再取最靠前名次。"""
    rank, matched, _entry = find_best_brand_hit_scoped(
        entries, match_name, scope, skip_name=skip_name,
    )
    return rank, matched


def _is_major_section_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    header = _parse_markdown_header(stripped)
    if header:
        level, content = header
        return level == 2 or bool(SECTION_TITLE_RE.match(content))
    return bool(_MAJOR_SECTION_RE.match(stripped))


def _is_rankable_content_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    if LIST_ITEM_RE.match(stripped) or BULLET_ITEM_RE.match(stripped):
        return True
    plain = re.sub(r"^\*+\s*|\*+$", "", stripped)
    return bool(NUMBERED_TITLE_RE.match(plain))


def _is_company_nomination_line(line: str) -> bool:
    """Appearance 只计「提名公司」的行，不计成立时间/核心优势等字段 bullet。"""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    header = _parse_markdown_header(stripped)
    if header:
        return _company_from_numbered_heading(header[1]) is not None
    plain = re.sub(r"^\*\*|\*\*$", "", stripped).strip()
    if _company_from_numbered_heading(plain):
        return True
    list_match = LIST_ITEM_RE.match(stripped)
    if list_match:
        name = _extract_list_item_name(list_match.group(4))
        return bool(name) and _looks_like_company_list_name(name)
    bullet = BULLET_ITEM_RE.match(stripped)
    if bullet:
        name = _extract_list_item_name(bullet.group(1) or bullet.group(2) or "")
        if not name or not _looks_like_company_list_name(name):
            return False
        # 字段短标签已在 _looks_like_company_list_name 拦掉；无公司后缀的短词也不计
        return any(hint in name for hint in _CORP_NAME_HINTS) or bool(_COMPANY_ENTITY_HINT_RE.search(name))
    if NUMBERED_TITLE_RE.match(plain):
        name = _extract_list_item_name(NUMBERED_TITLE_RE.match(plain).group(2))
        return bool(name) and _looks_like_company_list_name(name)
    return False


def appearance_order_rank_scoped(
    text: str,
    match_line: Callable[[str], bool],
    scope: str,
) -> int | None:
    """Rank within major sections that contain the brand; prefer scope-best section."""
    lines = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip() for raw in text.splitlines()]
    scope_text = str(scope or "").strip()

    section_ranges: list[tuple[int, int, int]] = []
    current_start: int | None = None
    current_score = -1
    for index, line in enumerate(lines):
        if not line or not _is_major_section_line(line):
            continue
        if current_start is not None:
            section_ranges.append((current_start, index, current_score))
        current_start = index
        current_score = ranking_category_scope_score(_extract_category_name(line), scope_text) if scope_text else 0
    if current_start is not None:
        section_ranges.append((current_start, len(lines), current_score))

    def rank_in_range(start: int, end: int) -> int | None:
        order = 0
        for line in lines[start + 1:end]:
            if not line or _is_major_section_line(line):
                continue
            if not _is_company_nomination_line(line):
                continue
            order += 1
            if match_line(line):
                return order
        return None

    hits: list[tuple[int, int]] = []
    for start, end, score in section_ranges:
        rank = rank_in_range(start, end)
        if rank is not None:
            hits.append((score, rank))

    if hits:
        best_score = max(score for score, _ in hits)
        threshold = max(best_score * 0.45, 100) if scope_text else -1
        preferred = [rank for score, rank in hits if score >= threshold]
        if preferred:
            return min(preferred)
        return min(rank for _, rank in hits)

    order = 0
    for line in lines:
        if not _is_company_nomination_line(line):
            continue
        order += 1
        if match_line(line):
            return order
    return None


def find_best_brand_rank(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> tuple[int | float | None, bool]:
    """Return best (smallest) rank among matched entries; prefer categorized over flat."""
    categorized: list[dict[str, Any]] = []
    flat: list[dict[str, Any]] = []
    matched = False
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name or not match_name(name):
            continue
        if skip_name and skip_name(name):
            continue
        if _is_non_rank_category(entry.get("category")):
            continue
        matched = True
        if entry.get("category"):
            categorized.append(entry)
        else:
            flat.append(entry)
    winner = _pick_best_rank_entry(categorized) or _pick_best_rank_entry(flat)
    if winner is not None:
        return float(winner["rank"]), True
    return None, matched


def find_best_brand_entry_scoped(
    entries: list[dict[str, Any]],
    match_name: Callable[[str], bool],
    scope: str,
    *,
    skip_name: Callable[[str], bool] | None = None,
) -> dict[str, Any] | None:
    """同 find_best_brand_rank_scoped，返回取胜的那条（含 category）。"""
    _rank, _matched, entry = find_best_brand_hit_scoped(
        entries, match_name, scope, skip_name=skip_name,
    )
    return entry



