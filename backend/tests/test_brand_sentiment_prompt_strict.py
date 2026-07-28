"""ponytail: 情感规则文案自检 — 确保收紧条款在 prompt 里。"""

from app.services.deepseek_client import DeepseekClient


def test_sentiment_prompt_is_stricter():
    # 不打真实 API：检查方法源码字符串含收紧关键句
    import inspect

    src = inspect.getsource(DeepseekClient.classify_brand_answer_sentiments)
    assert "口径适中" in src
    assert "拿不准时优先 neutral" not in src
    assert "王牌" in src or "优势亮点" in src
    assert "temperature=0.1" in src


if __name__ == "__main__":
    test_sentiment_prompt_is_stricter()
    print("ok")
