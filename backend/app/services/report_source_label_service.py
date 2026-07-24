"""售前/周期报告：信源网站类别与汉字站名（对齐门户 sourceCategory / 信源分析口径）。"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 常见域名 → 汉字站名；与门户 useSourceAnalysis.KNOWN_SITE_LABELS / sourceSiteLabel 对齐并扩展
_DOMAIN_CN_NAMES: dict[str, str] = {
    "163.com": "网易",
    "weibo.com": "微博",
    "sina.com.cn": "新浪",
    "sohu.com": "搜狐",
    "qq.com": "腾讯",
    "douyin.com": "抖音",
    "iesdouyin.com": "抖音",
    "xiaohongshu.com": "小红书",
    "xhslink.com": "小红书",
    "zhihu.com": "知乎",
    "bilibili.com": "哔哩哔哩",
    "b23.tv": "哔哩哔哩",
    "baidu.com": "百度",
    "baijiahao.baidu.com": "百家号",
    "baike.baidu.com": "百度百科",
    "zhidao.baidu.com": "百度知道",
    "tieba.baidu.com": "百度贴吧",
    "aiqicha.baidu.com": "爱企查",
    "search.quark.cn": "夸克",
    "quark.cn": "夸克",
    "zgswcn.com": "中国商报网",
    "cnblogs.com": "博客园",
    "csdn.net": "CSDN",
    "jianshu.com": "简书",
    "toutiao.com": "今日头条",
    "ixigua.com": "西瓜视频",
    "thepaper.cn": "澎湃新闻",
    "ifeng.com": "凤凰网",
    "36kr.com": "36氪",
    "huxiu.com": "虎嗅",
    "tianyancha.com": "天眼查",
    "qcc.com": "企查查",
    "qichacha.com": "企查查",
    "jd.com": "京东",
    "tmall.com": "天猫",
    "taobao.com": "淘宝",
    "douban.com": "豆瓣",
    "gov.cn": "政府网站",
    "wikipedia.org": "维基百科",
    "zh.wikipedia.org": "维基百科",
    "mp.weixin.qq.com": "微信公众号",
    "weixin.qq.com": "微信",
    "docin.com": "豆丁网",
    "doc88.com": "道客巴巴",
    "jiemian.com": "界面新闻",
    "yiche.com": "易车",
    "autohome.com.cn": "汽车之家",
    "zhipin.com": "BOSS直聘",
    "maigoo.com": "买购APP",
    "smzdm.com": "什么值得买",
    "to8to.com": "土巴兔装修网",
    "shangyexinzhi.com": "商业新知",
    "lieju.com": "济南列举网",
    "liebiao.com": "列表网",
    "dzwww.com": "大众网",
    "pchouse.com.cn": "PChouse太平洋家居网",
    # 户外/招标等监测常见域（引用 site 票已验证）
    "jcdecaux.com.cn": "德高广告",
    "chinabidding.com.cn": "中国采购与招标网",
    "jobui.com": "职友集",
    "hezegd.com": "菏泽广电网",
}

_CATEGORY_RULES: list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = [
    ("encyclopedia", "百科", ("百科",), ("baike.baidu.com", "wikipedia.org", "wiki"), ()),
    ("government", "政府/事业", ("人民政府", "政务", "gov.cn"), (), (".gov.cn", ".gov")),
    (
        "enterprise",
        "企业库/工商",
        ("企查查", "天眼查", "爱企查", "工商信息", "企业信用"),
        ("tianyancha.com", "qcc.com", "qichacha.com", "aiqicha.baidu.com", "gsxt.gov.cn"),
        (),
    ),
    ("qa", "问答社区", ("问答", "知乎"), ("zhihu.com", "zhidao.baidu.com", "stackoverflow.com"), ()),
    (
        "social",
        "社交媒体",
        ("微博", "小红书"),
        (
            "weibo.com",
            "weixin.qq.com",
            "mp.weixin.qq.com",
            "douyin.com",
            "xiaohongshu.com",
            "xhslink.com",
        ),
        (),
    ),
    ("forum", "论坛社区", ("论坛", "贴吧"), ("tieba.baidu.com", "v2ex.com", "douban.com", "bbs."), ()),
    (
        "video",
        "视频平台",
        ("视频", "bilibili", "b站"),
        ("bilibili.com", "b23.tv", "youku.com", "iqiyi.com", "v.qq.com"),
        (),
    ),
    (
        "media",
        "行业媒体",
        ("媒体", "新闻", "资讯", "报道"),
        ("sohu.com", "163.com", "sina.com.cn", "ifeng.com", "thepaper.cn", "36kr.com", "huxiu.com"),
        (),
    ),
    (
        "ecommerce",
        "电商/交易",
        ("旗舰店", "商城", "店铺"),
        ("taobao.com", "tmall.com", "jd.com", "1688.com"),
        (),
    ),
    ("official", "官网/企业站点", ("官网", "官方网站", "homepage", "企业介绍", "关于我们"), (), ()),
]

_TITLE_SITE_RE = re.compile(r"(?:_|[-–—]\s*)([\u4e00-\u9fffA-Za-z0-9·]{2,24})$")
_PUBLISHER_HINT_RE = re.compile(
    r"网|新闻|日报|晚报|时报|媒体|资讯|头条|百科|论坛|博客|视频|电台|电视|客户端|周刊|杂志|值得买|招标|广告|职友"
)
_BRAND_LIKE_RE = re.compile(r"集团|有限公司|股份有限|广告投放|控股")
_CACHE_PATH = Path(__file__).resolve().parents[2] / ".cache" / "site_label_cache.json"


def normalize_host(raw: str | None) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    try:
        url = text if "://" in text else f"https://{text}"
        host = (urlparse(url).hostname or "").removeprefix("www.")
        return host
    except Exception:
        return text.replace("https://", "").replace("http://", "").removeprefix("www.").split("/")[0]


def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _normalize_site_candidate(raw: str | None) -> str:
    return str(raw or "").strip().split(",")[0].split("，")[0].split("/")[0].strip()


def _brand_name_tokens(brand: str) -> list[str]:
    text = re.sub(r"\s+", "", str(brand or ""))
    if not text:
        return []
    tokens: list[str] = []
    head = re.match(r"^([\u4e00-\u9fff]{2,8})", text)
    if head:
        core = head.group(1)
        tokens.append(core)
        for n in (2, 3, 4):
            if len(core) >= n:
                tokens.append(core[:n])
    # 去掉「控股/集团」前的主体
    clipped = re.split(r"控股|集团|有限|股份", text, maxsplit=1)[0]
    if clipped and len(clipped) >= 2:
        tokens.append(clipped)
    return list(dict.fromkeys(t for t in tokens if len(t) >= 2))


def _looks_like_publisher(name: str, *, brand: str = "") -> bool:
    """对齐门户：中文发布方名；排除品牌主体串。"""
    text = _normalize_site_candidate(name)
    if not text or not _has_chinese(text):
        return False
    if "." in text or "://" in text:
        return False
    if len(text) > 24:
        return False
    if _BRAND_LIKE_RE.search(text):
        return False
    compact = re.sub(r"\s+", "", text)
    for token in _brand_name_tokens(brand):
        if token and token in compact:
            return False
    if _PUBLISHER_HINT_RE.search(text):
        return True
    return len(text) <= 10


def pick_site_label_from_votes(
    votes: dict[str, int] | Counter[str] | None,
    *,
    brand: str = "",
) -> str | None:
    if not votes:
        return None
    ranked = sorted(
        ((_normalize_site_candidate(name), int(count)) for name, count in dict(votes).items()),
        key=lambda row: (-row[1], -len(row[0]), row[0]),
    )
    for name, _count in ranked:
        if _looks_like_publisher(name, brand=brand):
            return name[:24]
    # 次优：任意中文短名（仍排除品牌主体）
    for name, _count in ranked:
        text = _normalize_site_candidate(name)
        if not text or not _has_chinese(text) or "." in text:
            continue
        if _BRAND_LIKE_RE.search(text):
            continue
        compact = re.sub(r"\s+", "", text)
        if any(token and token in compact for token in _brand_name_tokens(brand)):
            continue
        return text[:24]
    return None


def lookup_domain_cn_name(host: str | None) -> str | None:
    """仅查静态字典。LLM 缓存必须经候选校验后才能写回 _DOMAIN_CN_NAMES（A+C）。"""
    text = normalize_host(host)
    if not text:
        return None
    candidates = sorted(_DOMAIN_CN_NAMES.items(), key=lambda kv: len(kv[0]), reverse=True)
    for key, label in candidates:
        if not label:
            continue
        if text == key or text.endswith(f".{key}"):
            return label
    return None


_LEGAL_NAME_TAILS = (
    "控股集团有限公司",
    "集团有限公司",
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "控股集团",
    "集团",
    "公司",
)


def short_entity_label(*candidates: str | None) -> str:
    """2b：品牌/竞品展示名（简称优先，去掉法人后缀）。"""
    for raw in candidates:
        text = re.sub(r"\s+", "", str(raw or "").strip())
        if not text:
            continue
        for tail in _LEGAL_NAME_TAILS:
            if text.endswith(tail) and len(text) > len(tail) + 1:
                text = text[: -len(tail)]
                break
        if _has_chinese(text):
            head = re.match(r"^([\u4e00-\u9fffA-Za-z0-9]{2,12})", text)
            return (head.group(1) if head else text)[:24]
        if 1 < len(text) <= 24:
            return text
    return ""


def lookup_official_site_label(
    host: str | None,
    official_site_labels: dict[str, str] | None,
) -> str | None:
    """官网豁免：host 命中配置的品牌/竞品主站 → 返回 2b 展示名。"""
    text = normalize_host(host)
    if not text or not official_site_labels:
        return None
    ranked = sorted(
        ((normalize_host(k), str(v).strip()) for k, v in official_site_labels.items()),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    for key, label in ranked:
        if not key or not label:
            continue
        if text == key or text.endswith(f".{key}"):
            return label[:24]
    return None


def build_official_site_label_map(
    entries: list[tuple[str | None, str | None]],
) -> dict[str, str]:
    """[(url_or_host, display_label), ...] → {host: label}。"""
    out: dict[str, str] = {}
    for raw_url, raw_label in entries:
        host = normalize_host(raw_url)
        label = str(raw_label or "").strip()
        if host and label:
            out[host] = label[:24]
    return out


def load_official_site_labels_for_brand(brand: str, db=None) -> dict[str, str]:
    """从 BrandAsset.official_url + 竞品 website_url 拉官网豁免表（暂不写 lead 字段）。"""
    brand_key = re.sub(r"\s+", "", str(brand or "").strip().lower())
    if not brand_key:
        return {}
    close = False
    if db is None:
        try:
            from app.core.database import SessionLocal

            db = SessionLocal()
            close = True
        except Exception as exc:
            logger.warning("official site labels skipped (no db): %s", exc)
            return {}
    try:
        from sqlalchemy import select

        from app.models.brand import BrandAsset, BrandCompetitor

        matched: BrandAsset | None = None
        for asset in db.scalars(select(BrandAsset).where(BrandAsset.deleted.is_(False))):
            for candidate in (
                asset.brand_short_name,
                asset.brand_name,
                asset.company_full_name,
            ):
                key = re.sub(r"\s+", "", str(candidate or "").strip().lower())
                if key and (key == brand_key or key in brand_key or brand_key in key):
                    matched = asset
                    break
            if matched is not None:
                break
        if matched is None:
            return {}

        brand_label = short_entity_label(
            matched.brand_short_name,
            matched.brand_name,
            matched.company_full_name,
            brand,
        )
        entries: list[tuple[str | None, str | None]] = []
        if matched.official_url and brand_label:
            entries.append((matched.official_url, brand_label))
        for row in db.scalars(
            select(BrandCompetitor).where(
                BrandCompetitor.tenant_id == matched.tenant_id,
                BrandCompetitor.deleted.is_(False),
                BrandCompetitor.status.is_(True),
            )
        ):
            if not row.website_url:
                continue
            label = short_entity_label(row.short_name, row.name)
            if label:
                entries.append((row.website_url, label))
        return build_official_site_label_map(entries)
    except Exception as exc:
        logger.warning("official site labels load failed: %s", exc)
        return {}
    finally:
        if close and db is not None:
            db.close()


def resolve_chinese_site_name(
    *,
    domain: str | None = None,
    url: str | None = None,
    title: str | None = None,
    site: str | None = None,
    site_votes: dict[str, int] | None = None,
    brand: str = "",
    official_site_labels: dict[str, str] | None = None,
) -> str:
    """汉字站名：字典 → 官网豁免 → 显式 site → site 票 → 标题尾部 → 域名。"""
    host = normalize_host(domain) or normalize_host(url) or normalize_host(site)
    known = lookup_domain_cn_name(host)
    if known:
        return known

    official = lookup_official_site_label(host, official_site_labels)
    if official:
        return official

    site_text = _normalize_site_candidate(site)
    if site_text and _looks_like_publisher(site_text, brand=brand):
        return site_text[:24]

    voted = pick_site_label_from_votes(site_votes, brand=brand)
    if voted:
        return voted

    title_text = str(title or "").strip()
    if title_text:
        match = _TITLE_SITE_RE.search(title_text)
        if match and _looks_like_publisher(match.group(1), brand=brand):
            return match.group(1)[:24]

    return host or "—"


def classify_source_category(
    *,
    domain: str | None = None,
    url: str | None = None,
    title: str | None = None,
    official_site_labels: dict[str, str] | None = None,
) -> str:
    """返回网站类别中文标签。"""
    host = normalize_host(domain) or normalize_host(url)
    if lookup_official_site_label(host, official_site_labels):
        return "官网/企业站点"
    text = f"{title or ''} {url or ''} {host}".lower()
    for _cid, label, keywords, domains, suffixes in _CATEGORY_RULES:
        if _cid == "official":
            continue
        if any(host.endswith(suf.lstrip(".")) or host.endswith(suf) for suf in suffixes if suf):
            return label
        if any(host == d or host.endswith(f".{d}") or d in text for d in domains if d):
            return label
        if any(kw.lower() in text for kw in keywords):
            return label
    for _cid, label, keywords, domains, suffixes in _CATEGORY_RULES:
        if _cid != "official":
            continue
        if any(kw.lower() in text for kw in keywords):
            return label
    return "官网/企业站点" if host and not any(ch.isdigit() for ch in host[:2]) else "其他"


def enrich_source_row(
    row: dict,
    *,
    brand: str = "",
    official_site_labels: dict[str, str] | None = None,
) -> dict:
    """给 top_sources / domain_stats 行补 site_cn / category_label。"""
    domain = str(row.get("domain") or "").strip()
    url = str(row.get("url") or "").strip()
    title = str(row.get("title") or "").strip()
    site = str(row.get("site") or "").strip()
    votes = row.get("site_votes")
    vote_map = dict(votes) if isinstance(votes, dict) else None
    if not domain:
        domain = normalize_host(url) or normalize_host(site)
    site_cn = resolve_chinese_site_name(
        domain=domain,
        url=url,
        title=title,
        site=site,
        site_votes=vote_map,
        brand=brand,
        official_site_labels=official_site_labels,
    )
    category = classify_source_category(
        domain=domain,
        url=url or domain,
        title=title,
        official_site_labels=official_site_labels,
    )
    return {
        **row,
        "domain": domain or "—",
        "site_cn": site_cn,
        "category_label": category,
    }


def _load_llm_cache() -> dict[str, str]:
    try:
        if not _CACHE_PATH.exists():
            return {}
        payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        return {
            str(k).strip().lower(): str(v).strip()
            for k, v in payload.items()
            if str(k).strip() and str(v).strip() and _has_chinese(str(v))
        }
    except Exception:
        return {}


def _save_llm_cache(cache: dict[str, str]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("site_label cache write failed: %s", exc)


def _needs_llm_label(site_cn: str | None, domain: str | None) -> bool:
    label = str(site_cn or "").strip()
    host = normalize_host(domain)
    if not host:
        return False
    if not label or label in {"—", "-"}:
        return True
    if label.lower() == host.lower():
        return True
    if not _has_chinese(label):
        return True
    return False


def resolve_missing_site_labels_with_llm(
    rows: list[dict],
    *,
    brand: str = "",
) -> dict[str, str]:
    """A+C：仅在有候选证据时让 LLM 从候选中选；选不出则不写缓存、保持域名。"""
    cache = _load_llm_cache()
    # C：清掉无法用候选复核的历史盲猜缓存（下次不再误用）
    evidence_items: list[dict] = []
    resolved: dict[str, str] = {}

    for row in rows:
        host = normalize_host(row.get("domain") or row.get("url"))
        if not host:
            continue
        # 静态字典已覆盖则跳过
        if host in _DOMAIN_CN_NAMES or any(
            host == k or host.endswith(f".{k}") for k in _DOMAIN_CN_NAMES
        ):
            continue

        votes = row.get("site_votes") if isinstance(row.get("site_votes"), dict) else {}
        site = _normalize_site_candidate(row.get("site"))
        candidates: list[str] = []
        for name, _count in sorted(votes.items(), key=lambda kv: -int(kv[1] or 0)):
            text = _normalize_site_candidate(name)
            if text and text not in candidates:
                candidates.append(text)
        if site and site not in candidates:
            candidates.insert(0, site)
        titles = []
        title = str(row.get("title") or "").strip()
        if title:
            titles.append(title)
        for extra in list(row.get("sample_titles") or [])[:3]:
            t = str(extra or "").strip()
            if t and t not in titles:
                titles.append(t)

        # C：没有「像发布方」的中文候选 → 不调 LLM，去掉盲缓存，回退域名
        viable = [c for c in candidates if _looks_like_publisher(c, brand=brand)]
        if not viable:
            if host in cache:
                cache.pop(host, None)
            continue

        cached = cache.get(host)
        if cached and cached in viable:
            resolved[host] = cached
            continue
        # 旧缓存不在合格候选内（如天创科技）→ 丢弃
        if cached and cached not in viable:
            cache.pop(host, None)

        evidence_items.append(
            {
                "domain": host,
                "candidates": viable,
                "titles": titles,
                "brand": brand,
            }
        )

    if evidence_items:
        try:
            from app.services.deepseek_client import DeepseekClient

            client = DeepseekClient()
            payload = client.resolve_domain_site_labels(evidence_items) if client.report_enabled else {}
        except Exception as exc:
            logger.warning("LLM site label resolve skipped: %s", exc)
            payload = {}

        changed = False
        cand_map = {str(item["domain"]): set(item.get("candidates") or []) for item in evidence_items}
        for host, label in (payload or {}).items():
            key = normalize_host(host)
            text = _normalize_site_candidate(label)
            if not key or not text:
                continue
            if text not in cand_map.get(key, set()):
                continue
            if not _looks_like_publisher(text, brand=brand):
                continue
            cache[key] = text[:24]
            resolved[key] = cache[key]
            _DOMAIN_CN_NAMES.setdefault(key, cache[key])
            changed = True
        if changed:
            _save_llm_cache(cache)
        elif evidence_items:
            # 可能只清理了坏缓存
            _save_llm_cache(cache)
    else:
        _save_llm_cache(cache)

    return resolved


def enrich_domain_rows(
    rows: list[dict],
    *,
    brand: str = "",
    use_llm: bool = True,
    official_site_labels: dict[str, str] | None = None,
) -> list[dict]:
    """映射/采信表：字典 → 官网豁免 → site票，再对仍回退域名的行按 A+C 调 LLM。"""
    labels = official_site_labels
    enriched = [
        enrich_source_row(row, brand=brand, official_site_labels=labels) for row in rows
    ]
    if not use_llm:
        return enriched
    missing_rows = [
        row
        for row in enriched
        if _needs_llm_label(row.get("site_cn"), row.get("domain"))
    ]
    if not missing_rows:
        return enriched
    resolve_missing_site_labels_with_llm(missing_rows, brand=brand)
    return [
        enrich_source_row(row, brand=brand, official_site_labels=labels) for row in rows
    ]


# ponytail: self-check — 常见域名映射与分类
assert resolve_chinese_site_name(domain="163.com") == "网易"
assert resolve_chinese_site_name(domain="baijiahao.baidu.com") == "百家号"
assert resolve_chinese_site_name(domain="jcdecaux.com.cn") == "德高广告"
assert resolve_chinese_site_name(
    domain="jobui.com",
    site_votes={"职友集": 10, "Jobui": 1},
) == "职友集"
assert (
    resolve_chinese_site_name(
        domain="imtcmkj.com",
        brand="艾迪亚控股集团有限公司",
        official_site_labels={"imtcmkj.com": "艾迪亚"},
    )
    == "艾迪亚"
)
assert short_entity_label("艾迪亚控股集团有限公司") == "艾迪亚"
assert classify_source_category(domain="zhihu.com") == "问答社区"
assert classify_source_category(domain="weibo.com") == "社交媒体"
assert (
    classify_source_category(
        domain="imtcmkj.com",
        official_site_labels={"imtcmkj.com": "艾迪亚"},
    )
    == "官网/企业站点"
)
