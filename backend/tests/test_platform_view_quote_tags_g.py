# -*- coding: utf-8 -*-
"""2026-08-20 - 对齐换皮版-G 原话标签口径。"""
from __future__ import annotations

from app.services.report_diagnosis_cockpit_service import _quote_tag_and_diag


def test_geo_drift_tag():
    tag, diag = _quote_tag_and_diag(
        brand="艾迪亚",
        rank=0,
        is_brand=False,
        summary="定西市目前暂无地铁系统，因此本地不存在传统意义上的“地铁广告公司”。",
    )
    assert tag == "地域跑偏"
    assert "错误地域" in diag


def test_same_name_steal_tag():
    tag, diag = _quote_tag_and_diag(
        brand="艾迪亚",
        rank=3,
        is_brand=True,
        summary="艾迪亚（南京艾迪亚数字娱乐，游戏美术CG公司）全称：南京艾迪亚动漫艺术有限公司。控股集团主体在后。",
    )
    assert tag == "同名抢戏"
    assert "挤" in diag or "主体" in diag


def test_same_name_split_tag():
    tag, diag = _quote_tag_and_diag(
        brand="艾迪亚",
        rank=1,
        is_brand=True,
        summary="“艾迪亚公司怎么样”需要先看具体是哪一家，因为叫“艾迪亚”的公司不止一个。",
    )
    assert tag == "同名先拆"


def test_classify_and_mid_rank():
    tag, _ = _quote_tag_and_diag(
        brand="艾迪亚",
        rank=1,
        is_brand=False,
        summary="地铁广告公司按资源归属可分两类：官方运营方与整合代理。",
    )
    assert tag == "分类框架"
    tag2, diag2 = _quote_tag_and_diag(
        brand="艾迪亚",
        rank=4,
        is_brand=False,
        summary="哪家好没有绝对答案，关键看预算与城市。",
    )
    assert tag2 == "未进前三"
    assert "第 4 名" in diag2
