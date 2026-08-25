"""补录分享页截图：隐藏 Continue、滚屏近似去重。"""

from PIL import Image

from app.services.share_page_screenshot_service import (
    HIDE_CHROME_JS,
    _frame_near_dup,
    _frame_sig,
)


def test_hide_chrome_covers_continue_with_deepseek():
    assert "Continue with DeepSeek" in HIDE_CHROME_JS
    assert "和 DeepSeek 继续聊" in HIDE_CHROME_JS


def test_hide_chrome_covers_doubao_cta_and_fixed_bottom():
    # 2026-08-25 - 豆包底栏「打开豆包」+ fixed/sticky 二次扫描
    assert "打开豆包" in HIDE_CHROME_JS
    assert "Continue with Doubao" in HIDE_CHROME_JS
    assert "position !== 'fixed'" in HIDE_CHROME_JS
    assert "position !== 'sticky'" in HIDE_CHROME_JS


def test_hide_chrome_covers_kimi_legal_footer():
    assert "月之暗面" in HIDE_CHROME_JS
    assert "legal-footer" in HIDE_CHROME_JS


def test_scroller_list_maps_qianwen_my_cn():
    from app.services.share_page_screenshot_service import _scroller_list

    sels = _scroller_list("qianwen.my.cn")
    assert any("page-content" in s for s in sels)
    assert sels[0]  # non-empty


def test_frame_near_dup_exact_and_close():
    base = Image.new("RGB", (200, 200), (240, 240, 240))
    for x in range(20, 80):
        for y in range(20, 80):
            base.putpixel((x, y), (30, 30, 30))
    sig_a = _frame_sig(base)

    twin = base.copy()
    sig_b = _frame_sig(twin)
    assert _frame_near_dup(sig_a, sig_b)

    noisy = base.copy()
    for x in range(20, 30):
        noisy.putpixel((x, 25), (32, 32, 32))
    sig_c = _frame_sig(noisy)
    assert _frame_near_dup(sig_a, sig_c)

    other = Image.new("RGB", (200, 200), (10, 10, 10))
    sig_d = _frame_sig(other)
    assert not _frame_near_dup(sig_a, sig_d)
