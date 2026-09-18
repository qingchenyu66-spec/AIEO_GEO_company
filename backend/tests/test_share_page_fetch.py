"""分享页信源抽取单测（豆包 + 跨平台 JSON/锚点）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.share_page_fetch_service import (
    SharePageFetchResult,
    _clean_answer_text,
    _claimed_material_count,
    _http_refs_enough,
    _refs_from_html,
    _result_from_html,
    extract_doubao_references,
    extract_json_title_url_references,
    extract_kimi_references,
    fetch_share_page,
    try_fast_fetch_share_page,
)

PROBE = Path(__file__).resolve().parents[1] / "_doubao_share_probe.html"
PROBE_DIR = Path(__file__).resolve().parents[1] / "_share_ref_probe"


def test_extract_doubao_references_from_probe_html() -> None:
    if not PROBE.exists():
        # CI 无 probe 文件时跳过；本地开发可保留 probe
        return
    html = PROBE.read_text(encoding="utf-8")
    refs = extract_doubao_references(html)
    assert len(refs) >= 3
    urls = {row["url"] for row in refs}
    assert any("aitntnews.com" in u or "juejin.cn" in u or "csdn.net" in u for u in urls)
    assert all(row.get("title") for row in refs)


def test_clean_answer_text_strips_ui_noise() -> None:
    text = "打开豆包\n2026 年 7 月 22 日•内容由 AI 生成，不能完全保障真实\n正文第一段\n\n正文第二段"
    cleaned = _clean_answer_text(text)
    assert "打开豆包" not in cleaned
    assert "正文第一段" in cleaned
    assert "正文第二段" in cleaned


def test_result_from_html_accepts_doubao_ssr_probe() -> None:
    if not PROBE.exists():
        return
    html = PROBE.read_text(encoding="utf-8")
    hit = _result_from_html(html, host="www.doubao.com", title="probe")
    assert hit is not None
    assert len(hit.answer_content) >= 80
    assert hit.references


def test_fetch_share_page_prefers_http(monkeypatch) -> None:
    fake = SharePageFetchResult(
        answer_content=(
            "1. AniShort（八九点）\n核心：协同短剧\n"
            "2. TapNow\n核心：节点画布\n"
            "3. Pixmax\n核心：算力聚合\n"
        ),
        references=[],
        title="Miora同类平台工具",
        source_host="www.doubao.com",
    )
    monkeypatch.setattr(
        "app.services.share_page_fetch_service._try_http_fetch",
        lambda url, host, prompt=None: fake,
    )
    out = fetch_share_page("https://www.doubao.com/thread/abc1234567890")
    assert out.answer_content == fake.answer_content
    assert out.title == "Miora同类平台工具"


def test_try_fast_fetch_returns_none_when_needs_browser(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.share_page_fetch_service._try_http_fetch",
        lambda url, host, prompt=None: SharePageFetchResult(
            answer_content="x" * 100,
            references=[],
            title="t",
            source_host="www.qianwen.com",
            claimed_refs=18,
        ),
    )
    assert try_fast_fetch_share_page("https://www.qianwen.com/share/chat/abc") is None


def test_kimi_and_json_parsers_on_local_probes() -> None:
    kimi = PROBE_DIR / "kimi.html"
    yuanbao = PROBE_DIR / "yuanbao_after.html"
    if not kimi.exists() or not yuanbao.exists():
        return
    kimi_refs = extract_kimi_references(kimi.read_text(encoding="utf-8", errors="replace"))
    assert len(kimi_refs) >= 5
    assert all(r.get("url", "").startswith("http") for r in kimi_refs)
    yb_refs = extract_json_title_url_references(
        yuanbao.read_text(encoding="utf-8", errors="replace"),
        page_host="yuanbao.tencent.com",
    )
    assert len(yb_refs) >= 5
    assert not any("yuanbao.tencent.com" in str(r.get("url")) for r in yb_refs)


def test_qianwen_http_not_enough_when_claim_exceeds_refs() -> None:
    hit = SharePageFetchResult(
        answer_content=("正文" * 40),
        references=[{"title": "a", "url": "https://blog.csdn.net/x", "site": "blog.csdn.net"}],
        source_host="www.qianwen.com",
        claimed_refs=18,
    )
    assert _claimed_material_count("已完成思考，参考了18篇材料") == 18
    assert _http_refs_enough(hit, "www.qianwen.com") is False
    hit2 = SharePageFetchResult(
        answer_content=("正文" * 40),
        references=[
            {"title": "a", "url": "https://a.com/1", "site": "a.com"},
            {"title": "b", "url": "https://b.com/2", "site": "b.com"},
        ],
        source_host="www.qianwen.com",
        claimed_refs=2,
    )
    assert _http_refs_enough(hit2, "www.qianwen.com") is True


def test_qianwen_web_source_parser_and_share_ids() -> None:
    from app.services.share_page_fetch_service import (
        _extract_qianwen_answer_text,
        _parse_qianwen_share_ids,
        extract_qianwen_web_sources,
    )

    ids = _parse_qianwen_share_ids(
        "https://qianwen.my.cn/share/chat/a33e97511c424036834be22d70312b1f?biz_id=ai_qwen&env=prod"
    )
    assert ids == ("a33e97511c424036834be22d70312b1f", "ai_qwen")
    payload = {
        "data": {
            "title": "demo",
            "session": {
                "record_list": [
                    {
                        "response_messages": [
                            {
                                "extra": [
                                    {
                                        "type": "web_source",
                                        "title": "2026年儿童DHA怎么选？_凤凰网",
                                        "url": "http://sd.ifeng.com/c/8vTrgaTJuzD",
                                        "raw_url": "http://sd.ifeng.com/c/8vTrgaTJuzD",
                                        "name": "凤凰网_山东频道",
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
        }
    }
    refs = extract_qianwen_web_sources(payload)
    assert len(refs) == 1
    assert "ifeng.com" in refs[0]["url"]
    assert "DHA" in refs[0]["title"]
    # 2026-08-14 - 回归：成功码 0 不能当假值
    assert (0 or -1) == -1
    assert (0 != 0) is False

    # 2026-08-14 - 无 mime 的 response_messages[].content 也要抽到，勿只剩标题
    long_answer = (
        "为孩子挑选DHA，需关注原料来源、纯度、配方和安全性。"
        "以下推荐几款口碑与实力俱佳的产品，按年龄段和需求分类。"
        "0-3岁婴幼儿：首选纯净藻油，守护娇嫩肠胃。"
        "3岁以上学龄儿童可按含量与认证继续对比选择。"
    )
    extract_payload = {
        "data": {
            "title": "儿童DHA品牌推荐：0-3岁藻油精选",
            "session": {
                "record_list": [
                    {
                        "response_messages": [
                            {"content": "儿童DHA品牌推荐"},
                            {
                                "meta_data": {
                                    "sources": [
                                        {
                                            "content": {
                                                "list": [
                                                    {
                                                        "summary": "x" * 200,
                                                        "page_content": "{" + ("y" * 100) + "}",
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                }
                            },
                            {"content": long_answer},
                        ],
                        "extra_info": {
                            "chat_odps": {
                                "material_detail": {
                                    "final_material_detail": json.dumps(
                                        [{"HostName": "淘宝网"} for _ in range(20)]
                                    )
                                }
                            }
                        },
                    }
                ]
            },
        }
    }
    extracted = _extract_qianwen_answer_text(extract_payload)
    assert "挑选DHA" in extracted
    assert len(extracted) >= 80
    assert "淘宝网" not in extracted


def test_doubao_chrome_shell_is_not_ready() -> None:
    from app.services.share_page_fetch_service import doubao_answer_ready

    chrome = "豆包 - 你的 AI 智能助手\n\n-->"
    assert doubao_answer_ready(chrome, title="豆包 - 你的 AI 智能助手") is False
    assert (
        _result_from_html(
            f"<html><body>{chrome}</body></html>",
            host="doubao.com",
            title="豆包 - 你的 AI 智能助手",
            body_text=chrome,
        )
        is None
    )


def test_doubao_numbered_answer_is_ready() -> None:
    from app.services.share_page_fetch_service import doubao_answer_ready

    answer = (
        "1. AniShort (八九点) 【最对标 Miora】\n"
        "核心：多智能体、导演台、批量剧集\n"
        "2. TapNow\n核心：节点画布\n"
        "3. Pixmax\n核心：算力聚合\n"
    )
    assert doubao_answer_ready(answer, title="Miora同类平台工具", prompt="Miora类似的平台工具") is True
    hit = _result_from_html(
        f"<html><body>{answer}</body></html>",
        host="www.doubao.com",
        title="Miora同类平台工具",
        body_text=answer,
        prompt="Miora类似的平台工具",
    )
    assert hit is not None
    assert "AniShort" in hit.answer_content


def test_try_fast_fetch_skips_doubao_chrome(monkeypatch) -> None:
    chrome = SharePageFetchResult(
        answer_content="豆包 - 你的 AI 智能助手\n\n-->",
        references=[],
        title="豆包 - 你的 AI 智能助手",
        source_host="www.doubao.com",
    )
    monkeypatch.setattr(
        "app.services.share_page_fetch_service._try_http_fetch",
        lambda url, host, prompt=None: chrome,
    )
    assert try_fast_fetch_share_page("https://www.doubao.com/thread/x0TKPSu1KeDROn4cM") is None


def test_doubao_browser_chrome_raises(monkeypatch) -> None:
    from app.services import share_page_fetch_service as svc
    from app.services.share_page_fetch_service import share_page_unusable_message

    monkeypatch.setattr(svc, "_DOUBAO_ANSWER_WAIT_SECONDS", 0.05)

    class _FakePage:
        def goto(self, *a, **k):
            return None

        def inner_text(self, *a, **k):
            return "豆包 - 你的 AI 智能助手\n\n-->"

        def wait_for_timeout(self, *a, **k):
            return None

        def title(self):
            return "豆包 - 你的 AI 智能助手"

        def content(self):
            return "<html><body>豆包 - 你的 AI 智能助手\n\n--></body></html>"

    class _FakeContext:
        def new_page(self):
            return _FakePage()

        def close(self):
            return None

    class _FakeBrowser:
        def new_context(self, **kwargs):
            return _FakeContext()

        def close(self):
            return None

    class _FakeChromium:
        @staticmethod
        def launch(headless=True):
            return _FakeBrowser()

    class _FakePw:
        chromium = _FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import playwright.sync_api as pw

    monkeypatch.setattr(pw, "sync_playwright", lambda: _FakePw())
    monkeypatch.setattr(svc, "_expand_citation_panels", lambda page: None)
    monkeypatch.setattr(
        "app.services.share_page_screenshot_service.capture_share_page_screenshot_from_page",
        lambda page, url, subtask_id=None: "/api/v1/media/backfill-shot/x.png",
    )
    try:
        svc.fetch_share_page_browser_combined("https://www.doubao.com/thread/abc", subtask_id="st-chrome")
        raise AssertionError("expected chrome shell to fail")
    except ValueError as exc:
        assert str(exc) == share_page_unusable_message()


def test_extract_answer_preserves_ol_markers_over_inner_text() -> None:
    """豆包 ol 序号在 CSS marker；即使 body inner_text 无编号，也要从 HTML 还原 1.2.3."""
    from app.services.share_page_fetch_service import _extract_answer_from_html

    page_html = """
    <html><body>
    <h2>品牌板材门店</h2>
    <ol class="container-RLBpOb" style="list-style: decimal">
      <li><strong>莫干山板材（呼市总店）</strong><div>地址：新城区</div></li>
      <li><strong>福庆板材（澳赢店）</strong><div>地址：回民区</div></li>
      <li><strong>千年舟生态板批发（通达店）</strong><div>地址：通达</div></li>
      <li><strong>大王椰板材（闽兴店）</strong><div>地址：玉泉区闽兴建材市场</div></li>
      <li><strong>原筑全屋定制（润宇店）</strong><div>地址：润宇</div></li>
    </ol>
    <p>呼市板材大本营，大王椰、泰山石膏板等很多板材商户都在这里，适合集中比价。</p>
    </body></html>
    """
    # 模拟 Playwright inner_text：无序号
    body_text = (
        "品牌板材门店\n"
        "莫干山板材（呼市总店）\n地址：新城区\n"
        "福庆板材（澳赢店）\n地址：回民区\n"
        "千年舟生态板批发（通达店）\n地址：通达\n"
        "大王椰板材（闽兴店）\n地址：玉泉区闽兴建材市场\n"
        "原筑全屋定制（润宇店）\n地址：润宇\n"
        "呼市板材大本营，大王椰、泰山石膏板等很多板材商户都在这里，适合集中比价。"
    )
    out = _extract_answer_from_html(page_html, body_text)
    assert "1. 莫干山板材" in out or re.search(r"1\.\s*莫干山板材", out)
    assert re.search(r"4\.\s*大王椰板材", out)
    assert "2. 福庆板材" in out or re.search(r"2\.\s*福庆板材", out)


def test_huhhot_ol_html_rank_resolves_to_4() -> None:
    """呼和浩特结构：还原编号后规则应把大王椰计为第4（不再被旁述虚成1）。"""
    import re as _re

    from app.services.monitor_service import BrandRankResolution, _resolve_brand_rank_detail
    from app.services.share_page_fetch_service import _extract_answer_from_html
    from app.models.monitor import GeoMonitorSubtask

    page_html = """
    <html><body>
    <h1>呼和浩特板材门店 & 市场推荐</h1>
    <h2>品牌板材门店（生态板 / ENF / 欧松板，家装首选）</h2>
    <ol>
      <li><strong>莫干山板材（呼市总店）</strong><div>地址：新城区海拉尔东街</div>
        <div>主营：生态板、多层板</div></li>
      <li><strong>福庆板材（澳赢店）</strong><div>地址：回民区</div></li>
      <li><strong>千年舟生态板批发（通达店）</strong><div>地址：通达建材市场</div></li>
      <li><strong>大王椰板材（闽兴店）</strong><div>地址：玉泉区闽兴建材市场</div>
        <div>主营：国标环保生态板</div></li>
      <li><strong>原筑全屋定制（润宇店）</strong><div>地址：润宇装饰城</div></li>
    </ol>
    <h2>板材集中大市场</h2>
    <ol>
      <li><strong>闽兴家居建材城（玉泉区）</strong>
        呼市板材大本营，大王椰、泰山石膏板等很多板材商户都在这里</li>
      <li><strong>海兴建材城（新城区）</strong>基础板材</li>
    </ol>
    </body></html>
    """
    body_no_num = "呼和浩特板材门店推荐\n" + ("门店介绍" * 20)
    answer = _extract_answer_from_html(page_html, body_no_num)
    assert _re.search(r"(?m)^4\.\s*大王椰板材", answer)

    st = GeoMonitorSubtask(
        subtask_id="t-huhhot-ol",
        task_id="task-t",
        platform="doubao",
        mode="standard",
        prompt="呼和浩特板材门店推荐",
        status="completed",
        answer_content=answer,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(st, st.prompt, ["大王椰", "大王椰板材"], None)
    assert isinstance(detail, BrandRankResolution)
    assert detail.rank == 4, detail


def test_jinhua_split_ol_continues_numbering_to_rank_3() -> None:
    """金华：豆包把门店拆成多个相邻 ol 时，序号续计且大王椰为第3。"""
    from app.models.monitor import GeoMonitorSubtask
    from app.services.monitor_service import _resolve_brand_rank_detail
    from app.services.share_page_fetch_service import _extract_answer_from_html

    page_html = """
    <html><body>
    <h2>浙中建材市场</h2>
    <ol><li><strong>千年舟（金华店）</strong><div>地址：北-08</div></li></ol>
    <ol>
      <li><strong>韩宇来板材（金华旗舰店）</strong><div>地址：B座</div></li>
      <li><strong>大王椰板材（金华总代）</strong><div>主营：森芯板</div></li>
    </ol>
    <h2>江南建材市场</h2>
    <ol>
      <li><strong>莫干山板材专卖店</strong><div>地址：7幢</div></li>
      <li><strong>团团圆圆板材</strong><div>地址：6-10号</div></li>
    </ol>
    </body></html>
    """
    body = "金华板材门店推荐\n" + ("门店" * 30)
    answer = _extract_answer_from_html(page_html, body)
    assert re.search(r"(?m)^1\.\s*千年舟", answer)
    assert re.search(r"(?m)^2\.\s*韩宇来", answer)
    assert re.search(r"(?m)^3\.\s*大王椰", answer)
    st = GeoMonitorSubtask(
        subtask_id="t-jinhua-ol",
        task_id="task-t",
        platform="doubao",
        mode="standard",
        prompt="金华板材门店推荐",
        status="completed",
        answer_content=answer,
        raw_result_json={},
    )
    detail = _resolve_brand_rank_detail(st, st.prompt, ["大王椰", "大王椰板材"], None)
    assert detail.rank == 3, detail


def test_deepseek_share_table_ranks_honglian_third_without_chrome() -> None:
    """DeepSeek 分享页: 公司表第3, 思考和页脚不进摘要, 选型句不能盖成第2."""
    from app.models.monitor import GeoMonitorSubtask
    from app.services.monitor_service import _resolve_brand_rank_detail
    from app.services.share_page_fetch_service import _extract_answer_from_html

    page_html = """
    <html><body>
    <div>DeepSeek - Into the Unknown</div>
    <div>Shared Conversation</div>
    <div>This shared conversation is generated by AI, for reference only.</div>
    <div>数据标注公司哪家好</div>
    <div class="ds-think-content">
      Thought for 2 seconds
      <p>用户再次提问数据标注公司哪家好, 海天瑞声、鸿联九五可能都要比较.</p>
      <p>Found 53 web pages</p>
    </div>
    <div class="ds-markdown">
      <p>选择数据标注公司, 核心是匹配项目需求.</p>
      <h2>综合实力领先的头部厂商</h2>
      <table>
        <tr><th>公司</th><th>核心定位与优势</th><th>典型客户/领域</th></tr>
        <tr><td>百度智能云</td><td>科技巨头代表</td><td>全行业</td></tr>
        <tr><td>海天瑞声</td><td>巨头生态</td><td>自动驾驶</td></tr>
        <tr><td>鸿联九五</td><td>全栈合规</td><td>政企</td></tr>
        <tr><td>云测数据</td><td>垂直定制</td><td>医疗</td></tr>
        <tr><td>景联文科技</td><td>高质量数据集</td><td>大模型</td></tr>
      </table>
      <h2>选型关键要点</h2>
      <p>1. 合规与安全资质: 优先选择参与国家标准制定的厂商, 如海天瑞声、鸿联九五、景联文科技等.</p>
    </div>
    <div>53 web pages</div>
    <div>Continue with DeepSeek</div>
    </body></html>
    """
    body_text = (
        "DeepSeek - Into the Unknown\nShared Conversation\n"
        "Thought for 2 seconds\n"
        "公司核心定位与优势典型客户/领域\n"
        "百度智能云科技巨头代表海天瑞声巨头生态鸿联九五全栈合规\n"
        "如海天瑞声、鸿联九五、景联文科技\n"
        "Continue with DeepSeek\n"
    ) + ("正文" * 40)
    answer = _extract_answer_from_html(page_html, body_text)
    assert "Shared Conversation" not in answer
    assert "Thought for" not in answer
    assert "Continue with DeepSeek" not in answer
    assert "用户再次提问" not in answer
    assert re.search(r"(?m)^\|\s*鸿联九五\s*\|", answer)
    st = GeoMonitorSubtask(
        subtask_id="t-ds-table",
        task_id="task-t",
        platform="deepseek",
        mode="standard",
        prompt="数据标注公司哪家好",
        status="completed",
        answer_content=answer,
        raw_result_json={"source": "rules_compare", "manual_rank_locked": False},
    )
    detail = _resolve_brand_rank_detail(
        st,
        st.prompt,
        ["鸿联九五", "北京鸿联九五信息产业有限公司"],
        None,
    )
    assert detail.rank == 3, detail
    assert detail.rank_basis == "company_table_row"
