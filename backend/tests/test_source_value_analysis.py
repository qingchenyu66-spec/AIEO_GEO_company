"""渠道价值拆解缓存与正文抽取自检。"""

from __future__ import annotations

from app.services.source_article_fetch_service import html_to_plain_text, is_http_url
from app.services.source_value_analysis_service import (
    apply_cached_source_value_analyses,
    get_cached_source_value,
    set_cached_source_value,
)


def test_html_to_plain_text_strips_script() -> None:
    html = "<html><script>evil()</script><body><p>电梯广告攻略</p><p>覆盖北京线路</p></body></html>"
    text = html_to_plain_text(html)
    assert "evil" not in text
    assert "电梯广告攻略" in text
    assert "覆盖北京线路" in text


def test_is_http_url() -> None:
    assert is_http_url("https://example.com/a")
    assert not is_http_url("zhihu.com/question/1")
    assert not is_http_url("")


def test_source_value_cache_roundtrip(tmp_path, monkeypatch) -> None:
    from app.services import source_value_analysis_service as svc

    monkeypatch.setattr(svc, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(svc, "get_json_cache", lambda key: None)
    monkeypatch.setattr(svc, "set_json_cache", lambda *args, **kwargs: None)

    url = "https://example.com/article-elevator"
    assert get_cached_source_value(url) is None
    set_cached_source_value(
        url,
        value_analysis="电梯屏投放攻略向内容，易进选型答案池；建议补可核验案例。",
        title="电梯攻略",
        brand_name="艾迪亚",
        excerpt_len=120,
    )
    cached = get_cached_source_value(url)
    assert cached is not None
    assert "电梯屏" in cached


def test_apply_cached_overwrites_rule_text(tmp_path, monkeypatch) -> None:
    from app.services import source_value_analysis_service as svc

    monkeypatch.setattr(svc, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(svc, "get_json_cache", lambda key: None)
    monkeypatch.setattr(svc, "set_json_cache", lambda *args, **kwargs: None)

    url = "https://example.com/hsr-whitepaper"
    set_cached_source_value(
        url,
        value_analysis="高铁广告白皮书向内容，权威背书强；建议沉淀可引用结论页。",
        title="高铁白皮书",
    )
    modules = {
        "source_influence": {
            "rows": [
                {
                    "index": 1,
                    "title": "高铁白皮书",
                    "count": 4,
                    "value_analysis": "累计引用 4 次的高权重渠道，具备持续曝光与背书价值，建议保持内容更新频率。",
                }
            ]
        }
    }
    updated, misses = apply_cached_source_value_analyses(
        modules,
        top_sources=[{"title": "高铁白皮书", "url": url, "count": 4}],
    )
    assert misses == []
    assert "白皮书" in updated["source_influence"]["rows"][0]["value_analysis"]
    assert "累计引用" not in updated["source_influence"]["rows"][0]["value_analysis"]
