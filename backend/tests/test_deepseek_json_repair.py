"""Self-check: JSON repair + multi-desc prompt helpers."""

from app.services.deepseek_client import DeepseekClient, DeepseekApiError


def test_parse_json_payload_wraps_bad_slice():
    # 弯引号导致的坏 JSON 应被 repair 或升为 DeepseekApiError，不再抛裸 JSONDecodeError
    bad = '{"items":[{"id":"1","descriptions":["含“弯引号”的坏串"]}]}'
    try:
        DeepseekClient._parse_json_payload(bad)
    except DeepseekApiError:
        pass
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"unexpected {type(exc)}: {exc}") from exc


def test_parse_json_payload_repairs_trailing_comma():
    text = '{"items":[{"id":"1","descriptions":["国企背景","防火涂料优势"],}]}'
    payload = DeepseekClient._parse_json_payload(text)
    assert payload["items"][0]["id"] == "1"
    assert len(payload["items"][0]["descriptions"]) == 2


def test_parse_json_payload_closes_truncated_items():
    # 模型偶发只写到 item 结束，缺 items/root 收尾
    text = (
        '{"items":[{"id":"16264823","descriptions":["北京金隅涂料是金隅集团全资国企",'
        '"国家级高新技术企业和专精特新小巨人"]}'
    )
    payload = DeepseekClient._parse_json_payload(text)
    assert len(payload["items"][0]["descriptions"]) == 2


if __name__ == "__main__":
    test_parse_json_payload_wraps_bad_slice()
    test_parse_json_payload_repairs_trailing_comma()
    print("ok")
