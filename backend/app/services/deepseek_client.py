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

    @property
    def report_enabled(self) -> bool:
        return bool(self.api_key) and settings.deepseek_report_enabled

    @property
    def knowledge_enabled(self) -> bool:
        return bool(self.api_key) and settings.deepseek_knowledge_parse_enabled

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

    def generate_report_insights(
        self,
        *,
        brand_name: str,
        company_name: str | None,
        report_type: str,
        period_label: str,
        kpis: dict[str, Any],
        platform_stats: list[dict[str, Any]],
        sentiment_counts: dict[str, int],
        top_sources: list[dict[str, Any]],
        competitor_names: list[str],
        rule_highlights: list[str],
    ) -> dict[str, Any]:
        """基于监测快照生成 GEO 报告结论与诊断建议。"""
        report_type_label = {
            "diagnosis": "企业诊断",
            "weekly": "监测周报",
            "monthly": "监测月报",
            "annual": "监测年报",
            "comparison": "竞品对比报告",
            "periodic": "周期报告",
        }.get(report_type, "监测报告")

        from app.services.molizhishu_catalog_service import get_supported_platform_catalog

        platform_names = {
            str(item.get("code") or ""): str(item.get("name") or item.get("code") or "")
            for item in get_supported_platform_catalog()
        }
        platform_lines = []
        for row in platform_stats[:12]:
            code = str(row.get("platform") or "")
            label = platform_names.get(code) or code
            platform_lines.append(
                f"- {label}: 完成 {row.get('completed')}/{row.get('total')}，"
                f"提及率 {row.get('mention_rate')}%，平均排名 {row.get('avg_rank') or '—'}"
            )
        source_lines = [
            f"- {item.get('title') or item.get('url')}（{item.get('count')} 次）"
            for item in top_sources[:6]
        ]

        system_prompt = (
            "你是 GEO（生成式引擎优化）监测报告撰写专家。"
            "请根据真实监测 KPI 与平台数据，输出面向客户交付的结构化报告结论。"
            "不得编造未提供的数据，不得虚构平台或指标。只输出 JSON，不要解释。"
        )
        user_prompt = (
            f"品牌：{brand_name}\n"
            f"企业：{company_name or brand_name}\n"
            f"报告类型：{report_type_label}\n"
            f"统计周期：{period_label}\n\n"
            "核心 KPI：\n"
            f"- 品牌提及率：{kpis.get('mention_rate')}%\n"
            f"- 平均推荐排名：{kpis.get('avg_rank') or '—'}\n"
            f"- Top3 露出率：{kpis.get('top3_rate')}%\n"
            f"- 正面情绪占比：{kpis.get('positive_rate')}%\n"
            f"- 已完成样本：{kpis.get('completed_count')} 条\n"
            f"- 引用信源数：{kpis.get('source_count')} 个\n\n"
            f"情绪分布：{sentiment_counts}\n"
            f"纳入竞品：{('、'.join(competitor_names) if competitor_names else '未配置')}\n\n"
            "各平台表现：\n"
            f"{chr(10).join(platform_lines) or '- 暂无平台明细'}\n\n"
            "高频信源：\n"
            f"{chr(10).join(source_lines) or '- 暂无信源'}\n\n"
            "规则引擎初稿（可参考，勿照搬）：\n"
            f"{chr(10).join(f'- {line}' for line in rule_highlights) or '- 无'}\n\n"
            "请输出 JSON：\n"
            "{\n"
            '  "executive_summary": "80-160字执行摘要",\n'
            '  "highlights": ["3-5条核心结论，每条20-50字"],\n'
            '  "sentiment_summary": "口碑与情绪总结",\n'
            '  "strength_points": "优势亮点，可多句",\n'
            '  "weakness_points": "待改善项，可多句",\n'
            '  "recommendation": "可执行的 GEO 优化建议",\n'
            '  "health_score": 0-100 的整数\n'
            "}"
        )

        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
            max_tokens=1800,
            source="report-insights",
        )
        payload = self._parse_json_payload(content)
        if not isinstance(payload, dict):
            raise DeepseekApiError("DeepSeek 报告 JSON 格式错误")

        highlights = payload.get("highlights")
        if not isinstance(highlights, list):
            highlights = rule_highlights
        else:
            highlights = [str(item).strip() for item in highlights if str(item).strip()][:6] or rule_highlights

        try:
            health_score = int(payload.get("health_score"))
        except (TypeError, ValueError):
            health_score = None
        if health_score is not None:
            health_score = max(0, min(100, health_score))

        def _text(key: str) -> str | None:
            value = payload.get(key)
            if value is None:
                return None
            text = str(value).strip()
            return text or None

        return {
            "executive_summary": _text("executive_summary"),
            "highlights": highlights,
            "sentiment_summary": _text("sentiment_summary"),
            "strength_points": _text("strength_points"),
            "weakness_points": _text("weakness_points"),
            "recommendation": _text("recommendation"),
            "health_score": health_score,
        }

    def parse_knowledge_document(
        self,
        *,
        brand_name: str,
        company_name: str | None,
        file_name: str,
        document_text: str,
        truncated: bool,
    ) -> dict[str, Any]:
        """Extract GEO-oriented summary and keywords from enterprise knowledge text."""
        system_prompt = (
            "你是 GEO 企业知识库分析助手。请阅读企业上传的资料文本，"
            "提炼可用于品牌监测、报告撰写和 AI 引用追溯的结构化要点。"
            "不得编造资料中不存在的信息。只输出 JSON，不要解释。"
        )
        truncate_note = "（正文已截断，仅基于前段内容分析）" if truncated else ""
        user_prompt = (
            f"品牌：{brand_name}\n"
            f"企业：{company_name or brand_name}\n"
            f"文件名：{file_name}{truncate_note}\n\n"
            "资料正文：\n"
            f"{document_text}\n\n"
            "请输出 JSON：\n"
            "{\n"
            '  "summary": "120-220字摘要，说明资料核心内容",\n'
            '  "keywords": ["5-12个关键词或短语"],\n'
            '  "topics": ["2-5个主题标签，如产品说明/品牌故事/FAQ"],\n'
            '  "geo_points": ["3-6条可在 GEO 监测或报告中引用的要点，每条15-40字"]\n'
            "}"
        )
        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1600,
            source="knowledge-parse",
        )
        payload = self._parse_json_payload(content)
        if not isinstance(payload, dict):
            raise DeepseekApiError("DeepSeek 知识库 JSON 格式错误")

        def _list(key: str, *, limit: int) -> list[str]:
            raw = payload.get(key)
            if not isinstance(raw, list):
                return []
            items = [str(item).strip() for item in raw if str(item).strip()]
            return items[:limit]

        summary = str(payload.get("summary") or "").strip()
        if not summary:
            raise DeepseekApiError("DeepSeek 未返回摘要")

        return {
            "source": "deepseek",
            "model": self.model,
            "summary": summary,
            "keywords": _list("keywords", limit=12),
            "topics": _list("topics", limit=5),
            "geo_points": _list("geo_points", limit=6),
        }
