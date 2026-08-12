"""定制优化建议 docx → deck HTML。"""

from pathlib import Path

from app.services.report_custom_optimization_service import docx_to_optimization_parts


def _opt_path() -> Path | None:
    try:
        from scripts._jinyu_opt_docx_path import resolve_jinyu_opt_docx

        return resolve_jinyu_opt_docx()
    except FileNotFoundError:
        return None


def test_docx_optimization_parts_shape() -> None:
    path = _opt_path()
    if path is None:
        return
    parts = docx_to_optimization_parts(path)
    assert len(parts) >= 9
    joined = "\n".join(parts)
    assert "官方平台优化" in joined
    assert "opt-table--doc" in joined
    assert "六、总结" in joined
    assert "（续）" not in joined
    # 截图区序号不应进正文
    assert "所有的的续都得删除" not in joined
    assert not any(p.strip().startswith("1.") for p in parts)
    sec3 = next(p for p in parts if "三、平台分层运营" in p)
    assert sec3.count("<tr>") == 5  # thead + 4 平台行
    # 2026-08-06 - 四节 5 行勿拆 3+2 续页
    sec4_parts = [p for p in parts if "四、已有词组" in p]
    assert len(sec4_parts) == 1
    assert sec4_parts[0].count("<tr>") == 6  # thead + 5 词组
    assert "磨石地坪" in sec4_parts[0]
    assert "核电涂料" in sec4_parts[0]
    # 六、总结应合页
    sec6 = [p for p in parts if "六、总结" in p]
    assert len(sec6) == 1
    assert "一核" in sec6[0] and "四维" in sec6[0]
    # Word 风格关键词表：rowspan + doc 样式
    assert "opt-table--doc" in joined
    assert 'rowspan="4"' in joined
    assert "四大场景专项词" in joined
    assert "工业漆品牌推荐" in joined
    assert 'class="opt-col-kw"' in joined


def test_section_three_table_not_mixed_with_four() -> None:
    path = _opt_path()
    if path is None:
        return
    parts = docx_to_optimization_parts(path)
    sec3 = next(p for p in parts if "三、平台分层" in p)
    assert "防火涂料" not in sec3
    assert any("防火涂料" in p for p in parts)
