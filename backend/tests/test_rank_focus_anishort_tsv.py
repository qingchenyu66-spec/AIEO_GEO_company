# -*- coding: utf-8 -*-
"""八点八冒号/竖线卡 + 鸿联制表符表：规则不应算空。"""

from types import SimpleNamespace

from app.services.monitor_service import BrandRankResolution, _resolve_brand_rank_detail


def _sub(prompt: str, answer: str, platform: str = "doubao"):
    return SimpleNamespace(
        prompt=prompt,
        answer_content=answer,
        mention_context=None,
        all_rankings_json=[],
        mention_position=None,
        raw_result_json={},
        platform=platform,
        status="completed",
        mode="standard",
        subtask_id="t-focus",
        task_id="task-t",
    )


def test_anishort_emoji_section_colon_cards_rank_first() -> None:
    answer = """
AI 短剧 / 漫剧制作平台（按人群分类）
✅ 团队批量连载（多人协作、长剧集、角色统一）
AniShort：主打工业化短剧、漫剧协同创作，支持多人在线。
LibTV（LiblibAI）：无限画布 + 节点式工作流。
Pixmax：多画布协同管理大量分镜。
✅ 独立创作者 / 个人精品短剧
TapNow：节点式无限画布，影视质感强。
"""
    detail = _resolve_brand_rank_detail(
        _sub("做短剧用什么平台", answer),
        "南京八点八数字科技有限公司",
        ["南京八点八数字科技有限公司", "AniShort"],
        None,
    )
    assert isinstance(detail, BrandRankResolution)
    assert detail.rank == 1, detail
    assert detail.rank_basis in {"section_local", "secondary_section_local"}


def test_anishort_pipe_cards_rank_first() -> None:
    answer = """
✅ AI 短剧 / 漫剧制作平台（你提到的这批）
AniShort｜多人协同首选，无限画布节点化，剧本、分镜、审片全在画布，团队批量做漫剧
TapNow｜镜头可控强，推拉摇移、景深灯光精细调，大量短剧模板
小云雀 AI｜上传剧本自动拆角色
"""
    detail = _resolve_brand_rank_detail(
        _sub("做短剧用什么平台", answer),
        "南京八点八数字科技有限公司",
        ["AniShort"],
        None,
    )
    assert detail.rank == 1, detail


def test_honglian_tsv_service_table_ranks() -> None:
    answer = """
选择短信群发公司，关键是看业务场景。

📋 主流服务商一览

类型	服务商	核心优势	适合场景
综合云厂商	阿里云	超大并发承载	大型电商
综合云厂商	腾讯云	控制台友好	小程序
垂直通信服务商	鸿联九五	央企背景，四大运营商直连	金融政务
垂直通信服务商	梦网科技	5G消息头部	中大型企业

💎 总结与建议
金融、政务等强合规场景：优先考虑 鸿联九五。
"""
    detail = _resolve_brand_rank_detail(
        _sub("短信群发公司选哪家", answer, platform="deepseek"),
        "北京鸿联九五信息产业有限公司",
        ["北京鸿联九五信息产业有限公司", "鸿联九五"],
        None,
    )
    assert detail.rank == 3, detail
    assert detail.rank_basis == "company_table_row"


def test_honglian_ragged_tsv_folded_rows_still_rank() -> None:
    """DeepSeek 折行：缺类型列 + 无 tab 噪声行，仍能读到鸿联行序。"""
    answer = """
类型	服务商	核心优势	适合场景
综合云厂商	阿里云	超大并发承载，电商大促稳定性极强-
7
已使用阿里云、大型电商
腾讯云	控制台友好，上手简单-
华为云	政企、能源友好-
垂直通信服务商	鸿联九五	央企背景，四大运营商直连-
梦网科技	A股老牌通信企业-
"""
    detail = _resolve_brand_rank_detail(
        _sub("短信群发公司选哪家", answer, platform="deepseek"),
        "北京鸿联九五信息产业有限公司",
        ["鸿联九五"],
        None,
    )
    assert detail.rank == 4, detail
    assert detail.rank_basis == "company_table_row"
