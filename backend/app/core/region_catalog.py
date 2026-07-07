"""省级地区编码与展示名称（与前端 regionOptions.ts 保持同步）。"""

from __future__ import annotations

REGION_NAME_BY_CODE: dict[str, str] = {
    "110000": "北京",
    "120000": "天津",
    "130000": "河北",
    "140000": "山西",
    "150000": "内蒙古",
    "210000": "辽宁",
    "220000": "吉林",
    "230000": "黑龙江",
    "310000": "上海",
    "320000": "江苏",
    "330000": "浙江",
    "340000": "安徽",
    "350000": "福建",
    "360000": "江西",
    "370000": "山东",
    "410000": "河南",
    "420000": "湖北",
    "430000": "湖南",
    "440000": "广东",
    "450000": "广西",
    "460000": "海南",
    "500000": "重庆",
    "510000": "四川",
    "520000": "贵州",
    "530000": "云南",
    "540000": "西藏",
    "610000": "陕西",
    "620000": "甘肃",
    "630000": "青海",
    "640000": "宁夏",
    "650000": "新疆",
    "710000": "台湾",
    "810000": "香港",
    "820000": "澳门",
}


def region_display_name(region_code: str | None) -> str:
    code = str(region_code or "").strip()
    if not code:
        return "全部区域"
    return REGION_NAME_BY_CODE.get(code, code)


def normalize_region_codes(codes: list[str] | None) -> list[str]:
    """去重并过滤非法省级编码。"""
    if not codes:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for raw in codes:
        code = str(raw or "").strip()
        if not code or code in seen or code not in REGION_NAME_BY_CODE:
            continue
        seen.add(code)
        result.append(code)
    return result


def region_display_labels(codes: list[str] | None) -> str:
    normalized = normalize_region_codes(codes)
    if not normalized:
        return "全部区域"
    return "、".join(region_display_name(code) for code in normalized)


def region_submission_targets(codes: list[str] | None) -> list[str | None]:
    """模力单次任务仅支持 1 个 regionCode；多省时按省拆任务。空列表表示不限地区。"""
    normalized = normalize_region_codes(codes)
    if not normalized:
        return [None]
    return list(normalized)
