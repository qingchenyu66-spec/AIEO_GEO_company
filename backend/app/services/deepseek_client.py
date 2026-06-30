"""DeepSeek Open API client (OpenAI-compatible chat completions)."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class DeepseekApiError(RuntimeError):
    """DeepSeek API business or network error."""


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)


class DeepseekClient:
    def __init__(self) -> None:
        self.api_key = settings.deepseek_api_key.strip()
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.model = settings.deepseek_model
        self.timeout = settings.deepseek_timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and settings.deepseek_sentiment_keyword_enabled

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise DeepseekApiError("未配置 DEEPSEEK_API_KEY")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        source: str = "deepseek",
    ) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=self._headers(), json=body)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:800]
            raise DeepseekApiError(f"DeepSeek HTTP 错误：{exc.response.status_code} {detail}") from exc
        except httpx.HTTPError as exc:
            raise DeepseekApiError(f"DeepSeek 网络错误：{exc}") from exc
        except ValueError as exc:
            raise DeepseekApiError("DeepSeek 响应不是合法 JSON") from exc
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info("[deepseek] source=%s model=%s duration=%sms", source, self.model, duration_ms)

        choices = payload.get("choices") or []
        if not choices:
            raise DeepseekApiError("DeepSeek 未返回 choices")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise DeepseekApiError("DeepSeek 返回空内容")
        return content.strip()

    @staticmethod
    def _parse_json_payload(text: str) -> Any:
        raw = text.strip()
        block = _JSON_BLOCK_RE.search(raw)
        if block:
            raw = block.group(1).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start:end + 1])
            start = raw.find("[")
            end = raw.rfind("]")
            if start >= 0 and end > start:
                return json.loads(raw[start:end + 1])
            raise DeepseekApiError("DeepSeek 返回内容无法解析为 JSON") from None

    def extract_sentiment_phrases(
        self,
        *,
        brand_name: str,
        polarity: str,
        excerpts: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Extract brand sentiment phrases from numbered monitor excerpts."""
        if not excerpts:
            return []

        polarity_label = "正面" if polarity == "positive" else "负面"
        lines = []
        for index, item in enumerate(excerpts, start=1):
            lines.append(f"[{index}] {item['text']}")

        system_prompt = (
            "你是 GEO 品牌监测分析助手。请从 AI 回答摘录中提取与指定品牌相关的情绪关键词/短语，"
            "用于词云展示。只输出 JSON，不要解释。"
        )
        user_prompt = (
            f"品牌：{brand_name}\n"
            f"情感倾向：{polarity_label}\n\n"
            "摘录：\n"
            f"{chr(10).join(lines)}\n\n"
            "要求：\n"
            "1. 只提取与品牌评价相关的短语，4-16 个汉字为宜\n"
            "2. 短语必须能在对应编号摘录中找到原文（可去掉标点差异）\n"
            "3. 不要输出品牌名本身，不要输出「核心优势」「覆盖全国」等空泛词\n"
            "4. 最多 20 条\n"
            '5. 严格输出 JSON：{"keywords":[{"text":"短语","index":1}]}\n'
            "   index 为摘录编号（从 1 开始）"
        )

        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1200,
            source="sentiment-keywords",
        )
        payload = self._parse_json_payload(content)
        keywords = payload.get("keywords") if isinstance(payload, dict) else payload
        if not isinstance(keywords, list):
            raise DeepseekApiError("DeepSeek JSON 缺少 keywords 数组")

        results: list[dict[str, str]] = []
        for item in keywords:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if index < 1 or index > len(excerpts):
                continue
            source = excerpts[index - 1]
            source_text = source["text"]
            normalized_text = re.sub(r"\s+", "", text)
            normalized_source = re.sub(r"\s+", "", source_text)
            if normalized_text not in normalized_source and text not in source_text:
                continue
            results.append({
                "text": text,
                "subtask_id": source["subtask_id"],
                "task_id": source["task_id"],
            })
        return results
