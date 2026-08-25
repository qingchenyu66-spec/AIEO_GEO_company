"""信源网站类型：规则表 + 域名 LLM 缓存（对齐门户 sourceCategory）。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).resolve().parents[2] / ".cache" / "source_category_cache.json"

# (id, 中文标签, keywords, domains, host_suffixes)
_CATEGORY_RULES: list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = [
    ("encyclopedia", "百科", ("百科",), ("baike.baidu.com", "wikipedia.org", "wiki"), ()),
    ("government", "政府/事业", ("人民政府", "政务", "gov.cn"), (), (".gov.cn", ".gov")),
    (
        "enterprise",
        "企业库/工商",
        (
            "企查查",
            "天眼查",
            "爱企查",
            "工商信息",
            "企业信用",
            "电话邦",
            "黄页",
            "查号",
            "名录",
        ),
        (
            "tianyancha.com",
            "qcc.com",
            "qichacha.com",
            "aiqicha.baidu.com",
            "gsxt.gov.cn",
            # 2026-08-25 - 黄页/商户名录站归企业库，勿落「其他」
            "dianhua.cn",
            "mapbar.com",
            "58.com",
            "ganji.com",
            "chinahr.com",
            "jobui.com",
            "11467.com",
        ),
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
        (
            "媒体",
            "新闻",
            "资讯",
            "报道",
            "家居网",
            "汽车之家",
        ),
        (
            "sohu.com",
            "163.com",
            "sina.com.cn",
            "ifeng.com",
            "thepaper.cn",
            "36kr.com",
            "huxiu.com",
            # 2026-08-25 - 垂直行业媒体补规则，避免 pchouse 等落默认「其他」
            "pchouse.com.cn",
            "yiche.com",
            "autohome.com.cn",
            "maigoo.com",
            "smzdm.com",
            "jiemian.com",
            "to8to.com",
            "shangyexinzhi.com",
            "cnblogs.com",
            "jianshu.com",
            "csdn.net",
            "toutiao.com",
            "ixigua.com",
            "zgswcn.com",
            "dzwww.com",
            "lieju.com",
            "liebiao.com",
            "docin.com",
            "doc88.com",
        ),
        (),
    ),
    (
        "ecommerce",
        "电商/交易",
        ("旗舰店", "商城", "店铺"),
        ("taobao.com", "tmall.com", "jd.com", "1688.com"),
        (),
    ),
    (
        "official",
        "官网/企业站点",
        (
            "官网",
            "官方网站",
            "homepage",
            "企业介绍",
            "关于我们",
            "公司简介",
            "企业简介",
            "集团简介",
            "欢迎您访问",
            "欢迎访问",
        ),
        ("dwywood.com",),
        (),
    ),
]

CATEGORY_LABEL_BY_ID = {row[0]: row[1] for row in _CATEGORY_RULES}
CATEGORY_LABEL_BY_ID["other"] = "其他"
VALID_CATEGORY_IDS = frozenset(CATEGORY_LABEL_BY_ID)


def normalize_host(raw: str | None) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    try:
        url = text if "://" in text else f"https://{text}"
        return (urlparse(url).hostname or "").removeprefix("www.")
    except Exception:
        return text.replace("https://", "").replace("http://", "").removeprefix("www.").split("/")[0]


def registrable_domain(host: str) -> str:
    """粗粒度注册域：m.pchouse.com.cn → pchouse.com.cn。"""
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 3 and parts[-1] in {"cn", "uk", "jp", "au"} and len(parts[-2]) <= 3:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def category_label(category_id: str | None) -> str:
    key = str(category_id or "").strip()
    return CATEGORY_LABEL_BY_ID.get(key, CATEGORY_LABEL_BY_ID["other"])


def _match_rule(
    rule: tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    *,
    text: str,
    host: str,
) -> bool:
    _cid, _label, keywords, domains, suffixes = rule
    for suffix in suffixes:
        bare = suffix.lstrip(".")
        if host == bare or host.endswith(f".{bare}"):
            return True
    for domain in domains:
        if not domain:
            continue
        if host == domain or host.endswith(f".{domain}") or domain in text:
            return True
    for keyword in keywords:
        if keyword.lower() in text:
            return True
    return False


def _looks_like_corporate_site_page(raw_text: str, host: str) -> bool:
    """经销商/门店自建站：标题常写「公司简介」或「业务|公司名」但不含「官网」二字。"""
    if not host:
        return False
    text = re.sub(r"\s+", "", str(raw_text or ""))
    if not text:
        return False
    if any(
        token in text
        for token in (
            "公司简介",
            "企业简介",
            "集团简介",
            "企业介绍",
            "关于我们",
            "联系我们",
            "官方网站",
            "官网",
        )
    ):
        return True
    if any(suffix in text for suffix in ("股份有限公司", "有限责任公司", "有限公司", "集团有限公司")):
        if any(sep in text for sep in ("|", "_", "｜")):
            return True
        if any(token in text for token in ("装饰材料", "门店", "旗舰店", "专卖", "经销", "贸易")):
            return True
    return False


def classify_source_category_id(
    *,
    domain: str | None = None,
    url: str | None = None,
    title: str | None = None,
    site: str | None = None,
    official_site_labels: dict[str, str] | None = None,
    use_cache: bool = True,
) -> str:
    """返回类型 id（encyclopedia/media/official/other…）。"""
    from app.services.report_source_label_service import lookup_official_site_label

    host = normalize_host(domain) or normalize_host(url)
    if lookup_official_site_label(host, official_site_labels):
        return "official"
    if use_cache and host:
        cached = get_cached_category_id(host)
        if cached:
            return cached

    text = f"{title or ''} {site or ''} {url or ''} {host}".lower()
    raw_text = f"{title or ''} {site or ''} {url or ''} {host}"
    for rule in _CATEGORY_RULES:
        if rule[0] == "official":
            continue
        if _match_rule(rule, text=text, host=host):
            return rule[0]

    official_rule = next(rule for rule in _CATEGORY_RULES if rule[0] == "official")
    if _match_rule(official_rule, text=text, host=host):
        return "official"

    # 2026-08-25 - 经销商/门店自建站标题常无「官网」二字，用公司简介/公司全称等识别
    if host and _looks_like_corporate_site_page(raw_text, host):
        return "official"

    # 2026-08-25 - 未知域名默认「其他」，勿再虚高官网占比
    return "other"


def classify_source_category_label(
    *,
    domain: str | None = None,
    url: str | None = None,
    title: str | None = None,
    site: str | None = None,
    official_site_labels: dict[str, str] | None = None,
    use_cache: bool = True,
) -> str:
    return category_label(
        classify_source_category_id(
            domain=domain,
            url=url,
            title=title,
            site=site,
            official_site_labels=official_site_labels,
            use_cache=use_cache,
        )
    )


def _load_category_cache() -> dict[str, str]:
    try:
        if not _CACHE_PATH.exists():
            return {}
        payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        out: dict[str, str] = {}
        for key, value in payload.items():
            host = normalize_host(key)
            cid = str(value or "").strip()
            if host and cid in VALID_CATEGORY_IDS:
                out[host] = cid
        return out
    except Exception:
        return {}


def _save_category_cache(cache: dict[str, str]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        normalized = {
            normalize_host(k): str(v).strip()
            for k, v in cache.items()
            if normalize_host(k) and str(v).strip() in VALID_CATEGORY_IDS
        }
        _CACHE_PATH.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("source category cache write failed: %s", exc)


def get_cached_category_id(host: str | None) -> str | None:
    key = normalize_host(host)
    if not key:
        return None
    return _load_category_cache().get(key)


def merge_category_cache(updates: dict[str, str]) -> None:
    if not updates:
        return
    cache = _load_category_cache()
    changed = False
    for raw_host, raw_cid in updates.items():
        host = normalize_host(raw_host)
        cid = str(raw_cid or "").strip()
        if host and cid in VALID_CATEGORY_IDS and cache.get(host) != cid:
            cache[host] = cid
            changed = True
    if changed:
        _save_category_cache(cache)


def enrich_source_stat_row(
    row: dict[str, Any],
    *,
    official_site_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = str(row.get("url") or "").strip()
    host = normalize_host(url)
    category = classify_source_category_id(
        domain=host,
        url=url,
        title=str(row.get("title") or ""),
        site=str(row.get("site") or ""),
        official_site_labels=official_site_labels,
        use_cache=True,
    )
    return {
        **row,
        "category": category,
        "category_label": category_label(category),
    }


def enrich_source_stat_rows(
    rows: list[dict[str, Any]],
    *,
    official_site_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    return [enrich_source_stat_row(row, official_site_labels=official_site_labels) for row in rows]


def collect_domains_for_llm_labeling(
    rows: list[dict[str, Any]],
    *,
    official_site_labels: dict[str, str] | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """规则未命中且无缓存的域名，供离线 LLM 标注。"""
    cache = _load_category_cache()
    by_host: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        host = normalize_host(url)
        if not host:
            continue
        if host in cache:
            continue
        rule_id = classify_source_category_id(
            domain=host,
            url=url,
            title=str(row.get("title") or ""),
            site=str(row.get("site") or ""),
            official_site_labels=official_site_labels,
            use_cache=False,
        )
        if rule_id != "other":
            continue
        entry = by_host.setdefault(
            host,
            {
                "domain": host,
                "titles": [],
                "count": 0,
            },
        )
        entry["count"] += int(row.get("count") or 0)
        title = str(row.get("title") or "").strip()
        if title and title not in entry["titles"] and len(entry["titles"]) < 3:
            entry["titles"].append(title)
    ranked = sorted(by_host.values(), key=lambda item: -int(item.get("count") or 0))
    return ranked[: max(1, int(limit))]


def resolve_source_categories_with_llm(items: list[dict[str, Any]]) -> dict[str, str]:
    """离线 LLM：为未知域名选固定类型 id；无把握则跳过。"""
    if not items:
        return {}
    try:
        from app.services.deepseek_client import DeepseekClient

        client = DeepseekClient()
        if not client.report_enabled:
            return {}
        payload = client.resolve_domain_source_categories(items)
    except Exception as exc:
        logger.warning("LLM source category resolve skipped: %s", exc)
        return {}

    out: dict[str, str] = {}
    for host, cid in (payload or {}).items():
        key = normalize_host(host)
        category_id = str(cid or "").strip()
        if key and category_id in VALID_CATEGORY_IDS and category_id != "other":
            out[key] = category_id
    if out:
        merge_category_cache(out)
    return out


def enqueue_source_category_labeling(items: list[dict[str, Any]]) -> bool:
    """异步标注未知域名；无 Celery 时跳过。"""
    from app.core.config import settings

    if not settings.celery_enabled or not items:
        return False
    digest = str(abs(hash(tuple(sorted(str(item.get("domain") or "") for item in items[:20])))))
    dedupe_key = f"celery:enqueued:source-category-label:{digest}"
    try:
        from app.core.redis_client import delete_cache, get_redis_client, prefixed_key
        from redis.exceptions import RedisError

        client = get_redis_client()
        if client is not None:
            try:
                if not client.set(prefixed_key(dedupe_key), "1", ex=3600, nx=True):
                    return True
            except RedisError as exc:
                logger.warning("source category label dedupe failed: %s", exc)
                return False
        from app.tasks.monitor import label_unknown_source_categories

        label_unknown_source_categories.delay(items[:40])
        return True
    except Exception as exc:
        logger.warning("enqueue source category labeling failed: %s", exc)
        try:
            from app.core.redis_client import delete_cache

            delete_cache(dedupe_key)
        except Exception:
            pass
        return False


# ponytail: self-check
assert classify_source_category_id(domain="zhihu.com") == "qa"
assert classify_source_category_id(domain="news.pchouse.com.cn") == "media"
assert classify_source_category_id(domain="dianhua.cn", site="电话邦") == "enterprise"
assert classify_source_category_id(
    title="大王椰板材店",
    url="https://www.dianhua.cn/x",
    site="电话邦",
) == "enterprise"
assert classify_source_category_id(
    title="公司简介_海南装饰材料,海口装饰材料,海南旺顺祥业贸易有限公司",
    url="https://www.hkwsxy.com/about.html",
) == "official"
assert classify_source_category_id(
    title="海南装饰材料|海口装饰材料|海口旺顺祥业贸易有限公司",
    url="https://hkwsxy.com/",
) == "official"
assert classify_source_category_id(
    title="大王椰官方网站-饰面美学大师",
    url="https://m.dwywood.com/news/info/73.html",
) == "official"
assert classify_source_category_id(domain="unknown-vertical.example") == "other"
assert classify_source_category_id(
    domain="imtcmkj.com",
    official_site_labels={"imtcmkj.com": "艾迪亚"},
) == "official"
