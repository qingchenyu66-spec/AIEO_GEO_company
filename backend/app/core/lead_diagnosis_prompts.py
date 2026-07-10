"""售前诊断语义词校验。"""

from __future__ import annotations


def validate_lead_prompt_text(prompt: str) -> None:
    text = prompt.strip()
    if text.startswith("例如：") or text.startswith("例如:"):
        raise ValueError("请填写真实检测问题，不要使用「例如：」模板占位")
    if "XXX" in text or "xxx" in text:
        raise ValueError("请将模板中的 XXX 替换为实际品牌或业务关键词")


def normalize_lead_prompts(prompts: list[str]) -> list[str]:
    cleaned = [item.strip() for item in prompts if item and item.strip()]
    if not cleaned:
        raise ValueError("至少填写一个检测问题")
    if len(cleaned) > 5:
        raise ValueError("最多支持 5 个检测问题")
    for item in cleaned:
        validate_lead_prompt_text(item)
    return cleaned
