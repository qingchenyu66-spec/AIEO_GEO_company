"""模力文档平台表解析：说明列可含嵌套标签。"""

from app.services.molizhishu_catalog_service import _parse_platform_rows


def test_parse_qianwen_mobile_with_nested_code_in_description():
    # 2026-08-11 - 文档说明含 <code>search</code> 时旧正则会漏掉整行
    html = """
    <table>
    <tr><td><code>doubao</code></td><td>豆包</td><td>字节跳动旗下的智能 AI 助手。</td></tr>
    <tr><td><code>deepseek</code></td><td>DeepSeek</td><td>领先的国产自研大模型，性能强劲。</td></tr>
    <tr><td><code>deepseek_mobile</code></td><td>DeepSeek 移动端</td><td>DeepSeek 移动端版本。</td></tr>
    <tr><td><img src="/images/svg/qwen-color.svg"><code>qianwen_mobile</code></td>
    <td>通义千问移动端</td>
    <td>为保证信源返回，使用 <code>search</code> 模式时会默认开启深度思考，但不会额外计费；非深度思考模式正在适配中。</td></tr>
    <tr><td><code>yuanbao_mobile</code></td><td>元宝移动端</td><td>元宝的移动端版本。</td></tr>
    </table>
    <table>
    <tr><td><code>consumerTaskId</code></td><td>幂等标识</td><td>启用幂等。</td></tr>
    </table>
    """
    rows = _parse_platform_rows(html)
    codes = [item["code"] for item in rows]
    assert "qianwen_mobile" in codes
    assert "consumertaskid" not in codes
    assert "consumerTaskId".lower() not in codes
    qw = next(item for item in rows if item["code"] == "qianwen_mobile")
    assert qw["name"] == "通义千问移动端"
    assert "search" in qw["description"]
    assert "<code>" not in qw["description"]
    assert qw["channel"] == "mobile"
