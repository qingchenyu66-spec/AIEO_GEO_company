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

# (id, 中文标签, keywords, domains, host_suffixes) — 先命中先返回；official 单独后置
_CATEGORY_RULES: list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = [
    (
        "encyclopedia",
        "百科/知识库",
        (),
        (
            "baike.baidu.com",
            "baike.com",
            "baike.sogou.com",
            "wikipedia.org",
            "wiki",
        ),
        (),
    ),
    (
        "government",
        "政府/公共事业",
        ("人民政府", "政务", "公共资源交易"),
        (),
        (".gov.cn", ".gov"),
    ),
    (
        "enterprise",
        "企业库/工商信息",
        ("企查查", "天眼查", "爱企查", "启信宝", "工商信息", "企业信用", "水滴信用"),
        (
            "tianyancha.com",
            "qcc.com",
            "qichacha.com",
            "aiqicha.baidu.com",
            "gsxt.gov.cn",
            "qixin.com",
            "shuidiqiye.com",
            "qimingpian.com",
        ),
        (),
    ),
    (
        "recruitment",
        "招聘/职场",
        ("招聘", "直聘", "猎聘", "人才网", "求职", "看准网", "职友集"),
        (
            "zhipin.com",
            "liepin.com",
            "51job.com",
            "zhaopin.com",
            "kanzhun.com",
            "jobui.com",
            "chinahr.com",
            "lagou.com",
            "maimai.cn",
        ),
        (),
    ),
    (
        "qa",
        "问答社区",
        ("问答", "知乎"),
        ("zhihu.com", "zhidao.baidu.com", "wukong.com", "stackoverflow.com"),
        (),
    ),
    (
        "ranking",
        "行业榜单/测评",
        (
            "十大品牌",
            "排行榜",
            "品牌排行",
            "选购指南",
            "横评",
            "品牌推荐",
            "口碑排行",
            "十大品牌网",
        ),
        (
            "maigoo.com",
            "cnpp.cn",
            "cnpp100.com",
            "chinapp.com",
            "top10.cn",
        ),
        (),
    ),
    (
        "b2b",
        "B2B/黄页/渠道站",
        ("黄页", "电话邦", "查号", "名录", "招商加盟", "供应商", "顺企", "马可波罗"),
        (
            "dianhua.cn",
            "mapbar.com",
            "58.com",
            "ganji.com",
            "11467.com",
            "huicong.com",
            "makepolo.com",
            "chinabidding.com.cn",
            "b2b168.com",
            "51sole.com",
            "gys.cn",
            "hc360.com",
        ),
        (),
    ),
    (
        "local",
        "地图/本地生活",
        ("地图", "大众点评", "美团", "高德地图", "百度地图"),
        (
            "amap.com",
            "gaode.com",
            "dianping.com",
            "meituan.com",
            "map.baidu.com",
            "map.qq.com",
        ),
        (),
    ),
    (
        "ecommerce",
        "电商平台",
        (),
        (
            "taobao.com",
            "tmall.com",
            "jd.com",
            "1688.com",
            "pinduoduo.com",
            "yangkeduo.com",
            "dangdang.com",
            "amazon.cn",
            "amazon.com",
            "youzan.com",
        ),
        (),
    ),
    (
        "social",
        "社交/内容平台",
        ("微博", "小红书", "公众号", "百家号", "头条号"),
        (
            "weibo.com",
            "weibo.cn",
            "weixin.qq.com",
            "mp.weixin.qq.com",
            "douyin.com",
            "iesdouyin.com",
            "xiaohongshu.com",
            "xhslink.com",
            "bilibili.com",
            "b23.tv",
            "youku.com",
            "iqiyi.com",
            "v.qq.com",
            "toutiao.com",
            "m.toutiao.com",
            "ixigua.com",
            "baijiahao.baidu.com",
        ),
        (),
    ),
    (
        "media",
        "行业媒体/新闻",
        (
            "媒体",
            "新闻",
            "资讯",
            "报道",
            "家居网",
            "新闻网",
            "日报",
            "晚报",
        ),
        (
            "sohu.com",
            "163.com",
            "sina.com.cn",
            "sina.cn",
            "ifeng.com",
            "thepaper.cn",
            "36kr.com",
            "huxiu.com",
            "pchouse.com.cn",
            "yiche.com",
            "autohome.com.cn",
            "jiemian.com",
            "to8to.com",
            "shangyexinzhi.com",
            "cnblogs.com",
            "jianshu.com",
            "csdn.net",
            "zgswcn.com",
            "dzwww.com",
            "lieju.com",
            "liebiao.com",
            "docin.com",
            "doc88.com",
            "bjd.com.cn",
            "bjnews.com.cn",
            "eastmoney.com",
            "stockstar.com",
            "people.com.cn",
            "xinhuanet.com",
            "ce.cn",
            "stcn.com",
            "cnstock.com",
            "pedaily.cn",
        ),
        (),
    ),
    (
        "forum",
        "论坛/经验分享",
        ("论坛", "贴吧", "值得买", "经验"),
        (
            "tieba.baidu.com",
            "v2ex.com",
            "douban.com",
            "smzdm.com",
            "chiphell.com",
            "club.autohome.com.cn",
            "bbs.",
        ),
        (),
    ),
    (
        "official",
        "官网/自有阵地",
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

# 2026-08-25 - 旧缓存 video 并入社交/内容
CATEGORY_LEGACY_ALIASES: dict[str, str] = {"video": "social"}

# 2026-08-25 - 经销商 heuristic 勿误伤大平台子域（投资界/百度地图等）
_CORPORATE_HEURISTIC_DENY_SUFFIXES: tuple[str, ...] = (
    "baidu.com",
    "china.cn",
    "sina.com.cn",
    "sina.cn",
    "sohu.com",
    "163.com",
    "qq.com",
    "eastmoney.com",
    "cnstock.com",
    "pedaily.cn",
    "weibo.com",
    "zhihu.com",
    "toutiao.com",
    "ixigua.com",
    "apple.com",
    "google.com",
    "ctrip.com",
    "mapbar.com",
    "360.cn",
)


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


def normalize_category_id(category_id: str | None) -> str:
    cid = str(category_id or "").strip()
    return CATEGORY_LEGACY_ALIASES.get(cid, cid)


def category_label(category_id: str | None) -> str:
    key = normalize_category_id(category_id)
    return CATEGORY_LABEL_BY_ID.get(key, CATEGORY_LABEL_BY_ID["other"])


def _host_matches_domain(host: str, domain: str) -> bool:
    """host 精确或后缀匹配；禁止 jd.com 子串误伤 bjd.com.cn。"""
    if not host or not domain:
        return False
    if domain == "bbs.":
        return host.startswith("bbs.") or ".bbs." in host
    bare = domain.lstrip(".")
    return host == bare or host.endswith(f".{bare}")


def _host_on_deny_platform(host: str) -> bool:
    reg = registrable_domain(host)
    for suffix in _CORPORATE_HEURISTIC_DENY_SUFFIXES:
        if (
            _host_matches_domain(host, suffix)
            or _host_matches_domain(reg, suffix)
        ):
            return True
    return False


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
        if domain and _host_matches_domain(host, domain):
            return True
    for keyword in keywords:
        if keyword.lower() in text:
            return True
    return False


def _rule_category_for_host(host: str) -> str:
    """仅按 host 走规则表（不含标题 heuristic / 缓存）。"""
    if not host:
        return "other"
    text = host.lower()
    for rule in _CATEGORY_RULES:
        if rule[0] == "official":
            continue
        if _match_rule(rule, text=text, host=host):
            return rule[0]
    official_rule = next(rule for rule in _CATEGORY_RULES if rule[0] == "official")
    if _match_rule(official_rule, text=text, host=host):
        return "official"
    return "other"


def _prune_cache_entries(cache: dict[str, str]) -> dict[str, str]:
    """去掉与 host 规则表冲突的 LLM 缓存项。"""
    pruned: dict[str, str] = {}
    for host, cid in cache.items():
        rule_id = _rule_category_for_host(host)
        if rule_id != "other" and rule_id != cid:
            continue
        pruned[host] = cid
    return pruned


def _looks_like_corporate_site_page(raw_text: str, host: str) -> bool:
    """经销商/门店自建站：标题常写「公司简介」或「业务|公司名」但不含「官网」二字。"""
    if not host or _host_on_deny_platform(host):
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
        if any(token in text for token in ("装饰材料", "门店", "专卖", "经销", "贸易")):
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

    # 2026-08-25 - 规则表优先于 LLM 缓存，避免旧缓存覆盖 dianhua.cn 等已补域名规则
    if use_cache and host:
        cached = get_cached_category_id(host)
        if cached:
            return cached

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
            cid = normalize_category_id(str(value or "").strip())
            if host and cid in VALID_CATEGORY_IDS:
                out[host] = cid
        pruned = _prune_cache_entries(out)
        if len(pruned) != len(out):
            _save_category_cache(pruned)
            logger.info(
                "source category cache pruned: %d -> %d entries",
                len(out),
                len(pruned),
            )
        return pruned
    except Exception:
        return {}


def sanitize_category_cache() -> int:
    """主动清理与规则表冲突的缓存；返回删除条数。"""
    cache = _load_category_cache()
    if not _CACHE_PATH.exists():
        return 0
    try:
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        before = len(raw) if isinstance(raw, dict) else 0
    except Exception:
        before = len(cache)
    removed = max(0, before - len(cache))
    if removed:
        _save_category_cache(cache)
    return removed


def _save_category_cache(cache: dict[str, str]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        normalized = {
            normalize_host(k): normalize_category_id(str(v).strip())
            for k, v in cache.items()
            if normalize_host(k) and normalize_category_id(str(v).strip()) in VALID_CATEGORY_IDS
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
        cid = normalize_category_id(str(raw_cid or "").strip())
        if not host or cid not in VALID_CATEGORY_IDS:
            continue
        rule_id = _rule_category_for_host(host)
        if rule_id != "other" and rule_id != cid:
            continue
        if cache.get(host) != cid:
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
        category_id = normalize_category_id(str(cid or "").strip())
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
