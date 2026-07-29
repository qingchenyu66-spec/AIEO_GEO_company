"""DeepSeek Open API client (OpenAI-compatible chat completions)."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.system_config_service import get_runtime_config

logger = logging.getLogger(__name__)


class DeepseekApiError(RuntimeError):
    """DeepSeek API business or network error."""


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)


class DeepseekClient:
    def __init__(self) -> None:
        self.timeout = settings.deepseek_timeout_seconds

    def _api_key(self) -> str:
        return str(get_runtime_config("deepseek_api_key") or "").strip()

    def _base_url(self) -> str:
        return str(get_runtime_config("deepseek_base_url") or settings.deepseek_base_url).rstrip("/")

    def _model(self) -> str:
        return str(get_runtime_config("deepseek_model") or settings.deepseek_model)

    @property
    def api_key(self) -> str:
        return self._api_key()

    @property
    def base_url(self) -> str:
        return self._base_url()

    @property
    def model(self) -> str:
        return self._model()

    @property
    def enabled(self) -> bool:
        return bool(self._api_key()) and bool(get_runtime_config("deepseek_sentiment_keyword_enabled"))

    @property
    def report_enabled(self) -> bool:
        return bool(self._api_key()) and bool(get_runtime_config("deepseek_report_enabled"))

    @property
    def knowledge_enabled(self) -> bool:
        return bool(self._api_key()) and bool(get_runtime_config("deepseek_knowledge_parse_enabled"))

    @property
    def rank_fallback_enabled(self) -> bool:
        return bool(self._api_key()) and bool(settings.deepseek_rank_fallback_enabled)

    def _headers(self) -> dict[str, str]:
        api_key = self._api_key()
        if not api_key:
            raise DeepseekApiError("未配置 DEEPSEEK_API_KEY")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _http_client(self) -> httpx.Client:
        # 不走 Windows/Clash 系统代理，避免代理未启动时 WinError 10061
        return httpx.Client(timeout=self.timeout, trust_env=False)

    def get_account_balance(self) -> dict[str, Any]:
        """Query DeepSeek prepaid balance via GET /user/balance."""
        url = f"{self.base_url}/user/balance"
        try:
            with self._http_client() as client:
                response = client.get(url, headers={**self._headers(), "Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:800]
            raise DeepseekApiError(f"DeepSeek HTTP 错误：{exc.response.status_code} {detail}") from exc
        except httpx.HTTPError as exc:
            raise DeepseekApiError(f"DeepSeek 网络错误：{exc}") from exc
        except ValueError as exc:
            raise DeepseekApiError("DeepSeek 余额响应不是合法 JSON") from exc
        if not isinstance(payload, dict):
            raise DeepseekApiError("DeepSeek 余额响应格式错误")
        return payload

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
            with self._http_client() as client:
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
                chunk = raw[start:end + 1]
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    repaired = DeepseekClient._repair_json_like(chunk)
                    try:
                        return json.loads(repaired)
                    except json.JSONDecodeError as exc:
                        raise DeepseekApiError("DeepSeek 返回内容无法解析为 JSON") from exc
            start = raw.find("[")
            end = raw.rfind("]")
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError as exc:
                    raise DeepseekApiError("DeepSeek 返回内容无法解析为 JSON") from exc
            raise DeepseekApiError("DeepSeek 返回内容无法解析为 JSON") from None

    @staticmethod
    def _repair_json_like(text: str) -> str:
        """轻量修常见坏 JSON：中文弯引号、尾逗号、缺失收尾括号。"""
        s = (
            str(text or "")
            .replace("“", '"')
            .replace("”", '"')
            .replace("‘", "'")
            .replace("’", "'")
        )
        s = re.sub(r",\s*([}\]])", r"\1", s)
        # 2026-07-27 - 多要点输出偶发截断少 ]} - 按栈补全收尾
        stack: list[str] = []
        in_str = False
        esc = False
        for ch in s:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append(ch)
            elif ch == "}" and stack and stack[-1] == "{":
                stack.pop()
            elif ch == "]" and stack and stack[-1] == "[":
                stack.pop()
        if in_str:
            s += '"'
        while stack:
            opener = stack.pop()
            s += "}" if opener == "{" else "]"
        return s

    def classify_brand_answer_sentiments(
        self,
        *,
        brand_name: str,
        items: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """二次解析：对品牌相关回答做正/中/负归类。

        items: [{id, text}]，返回 [{id, sentiment}]，sentiment 为 positive|neutral|negative。
        """
        rows = [
            {
                "id": str(item.get("id") or "").strip(),
                "text": str(item.get("text") or "").strip()[:1200],
            }
            for item in items
            if str(item.get("id") or "").strip() and str(item.get("text") or "").strip()
        ]
        if not rows:
            return []
        numbered = "\n\n".join(
            f"[{index}] id={row['id']}\n{row['text']}"
            for index, row in enumerate(rows, start=1)
        )
        system_prompt = (
            "你是品牌舆情分析助手。根据 AI 搜索/问答原文，判断对指定品牌的情感倾向。"
            "口径适中：有清晰优势/认可可判正面，不要过度压成中性。只输出 JSON，不要解释。"
        )
        user_prompt = (
            f"品牌名称：{brand_name}\n"
            "请对下列编号摘录分别判定情感：positive（正面）、neutral（中性）、negative（负面）。\n"
            "规则：\n"
            "1. 只看该品牌在文中的评价口径，忽略无关竞品褒贬\n"
            "2. neutral：纯客观百科罗列（成立时间/产能数字/资质名录堆砌），几乎无优劣评价\n"
            "3. negative：明确批评、风险、投诉、不推荐、负面对比占主导；"
            "吊销/注销/经营异常/处罚/失信等工商合规硬风险即使是客观陈述也判 negative\n"
            "4. positive：推荐、优势、好评、认可、领先/王牌/开创、口碑与实力背书等；"
            "专精特新/高新等若作为优势亮点写出（而非冷冰冰名录）也可 positive\n"
            "5. 正负都有时看主导倾向；主导正面 → positive，主导负面 → negative，难分主次 → neutral\n"
            '6. 严格输出：{"items":[{"id":"...","sentiment":"positive|neutral|negative"}]}\n'
            "7. 必须覆盖全部输入 id\n\n"
            f"{numbered}"
        )
        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # 2026-07-28 - v2「优先 neutral」过严、正面被压没 - 回调适中口径（已弃用「拿不准就中性」）
            temperature=0.1,
            max_tokens=1200,
            source="brand-analysis-sentiment",
        )
        payload = self._parse_json_payload(content)
        raw_items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raise DeepseekApiError("DeepSeek JSON 缺少 items 数组")
        allowed = {"positive", "neutral", "negative"}
        known_ids = {row["id"] for row in rows}
        results: list[dict[str, str]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            sentiment = str(item.get("sentiment") or "").strip().lower()
            if item_id not in known_ids or sentiment not in allowed:
                continue
            results.append({"id": item_id, "sentiment": sentiment})
        return results

    def extract_brand_answer_descriptions(
        self,
        *,
        brand_name: str,
        items: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """抽取每条回答中对该品牌的有用独立要点（可多条），并附要点级情感。

        items: [{id, text}]，返回 [{id, descriptions: [{text, sentiment}, ...]}]。
        软上限约 8；确有更多独立有用信息可到 16。
        """
        rows = [
            {
                "id": str(item.get("id") or "").strip(),
                # 2026-07-27 - 长文只送 1200 易丢产品线/工程要点 - 提到 3600
                "text": str(item.get("text") or "").strip()[:3600],
            }
            for item in items
            if str(item.get("id") or "").strip() and str(item.get("text") or "").strip()
        ]
        if not rows:
            return []
        numbered = "\n\n".join(
            f"[{index}] id={row['id']}\n{row['text']}"
            for index, row in enumerate(rows, start=1)
        )
        system_prompt = (
            "你是品牌监测文案助手。根据 AI 回答原文，抽取关于指定品牌的全部有用独立要点，"
            "并为每条要点单独判定情感。只输出合法 JSON（双引号、无注释、无尾逗号），不要解释。"
        )
        user_prompt = (
            f"品牌名称：{brand_name}\n"
            "请对下列编号摘录各写若干条中文短描述（每条 12～36 字），并给每条 sentiment。\n"
            "规则：\n"
            "1. 只写与该品牌相关的内容，忽略无关竞品与导航/套话\n"
            "2. 客观陈述，不要加「我认为」\n"
            "3. 一个要点一条：企业属性、资质称号、产品线、代表工程、产能、风险事实等必须拆开，"
            "禁止合并成一句长话\n"
            "4. 通常 3～8 条；确有更多独立有用信息时可超过，最多 16 条；"
            "正文若明显含多段信息，不得只返回 1 条\n"
            "5. 文中未实质提及该品牌 → descriptions 用空数组\n"
            "6. 每条必须带 sentiment：positive|neutral|negative；"
            "吊销/注销/经营异常/处罚/失信/不具备合法经营等硬风险 → 必须 negative；"
            "纯成立时间/地址/注册资本罗列 → neutral；优势/推荐/认可 → positive\n"
            '7. 严格输出：{"items":[{"id":"...","descriptions":'
            '[{"text":"要点1","sentiment":"negative"}]}]}\n'
            "8. 必须覆盖全部输入 id；text 字符串内不要使用双引号\n\n"
            f"{numbered}"
        )
        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=2400,
            source="brand-analysis-description",
        )
        try:
            payload = self._parse_json_payload(content)
        except DeepseekApiError:
            # 2026-07-27 - 多要点 JSON 偶发坏格式 - 降温度重试一次
            content = self.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt
                        + "\n\n上次输出不是合法 JSON，请只重新输出 JSON 对象。",
                    },
                ],
                temperature=0,
                max_tokens=2400,
                source="brand-analysis-description-retry",
            )
            payload = self._parse_json_payload(content)
        raw_items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raise DeepseekApiError("DeepSeek JSON 缺少 items 数组")
        known_ids = {row["id"] for row in rows}
        allowed = {"positive", "neutral", "negative"}
        results: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if item_id not in known_ids:
                continue
            raw_descs = item.get("descriptions")
            if not isinstance(raw_descs, list):
                # 兼容旧单句字段
                single = str(item.get("description") or "").strip()
                raw_descs = [single] if single else []
            cleaned: list[dict[str, str]] = []
            seen: set[str] = set()
            for desc in raw_descs:
                sentiment = ""
                if isinstance(desc, dict):
                    text = str(desc.get("text") or desc.get("description") or "").strip()
                    sentiment = str(desc.get("sentiment") or "").strip().lower()
                else:
                    text = str(desc or "").strip()
                text = re.sub(r"\s+", "", text)
                if len(text) < 4:
                    continue
                if len(text) > 60:
                    text = text[:60]
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                if sentiment not in allowed:
                    sentiment = "neutral"
                cleaned.append({"text": text, "sentiment": sentiment})
                if len(cleaned) >= 16:
                    break
            results.append({"id": item_id, "descriptions": cleaned})
        return results

    def extract_sentiment_phrases(
        self,
        *,
        brand_name: str,
        polarity: str,
        excerpts: list[dict[str, str]],
        exclude_names: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Extract brand sentiment phrases from numbered monitor excerpts."""
        if not excerpts:
            return []

        polarity_label = "正面" if polarity == "positive" else "负面"
        lines = []
        for index, item in enumerate(excerpts, start=1):
            lines.append(f"[{index}] {item['text']}")

        exclude_block = ""
        cleaned_exclude = [str(name).strip() for name in (exclude_names or []) if str(name).strip()]
        if cleaned_exclude:
            exclude_block = (
                "禁止输出的实体名（品牌/竞品/别名），也勿输出仅含这些名字的短语：\n"
                + "、".join(cleaned_exclude[:40])
                + "\n\n"
            )

        system_prompt = (
            "你是 GEO 品牌监测分析助手。请从 AI 回答摘录中提取与指定品牌相关的情绪评价短语，"
            "用于正负面词云。只输出 JSON，不要解释。"
        )
        user_prompt = (
            f"品牌：{brand_name}\n"
            f"情感倾向：{polarity_label}\n\n"
            f"{exclude_block}"
            "摘录：\n"
            f"{chr(10).join(lines)}\n\n"
            "要求：\n"
            "1. 只提取对该品牌的评价/口碑短语（能力、口碑、风险、短板等），4-16 个汉字为宜\n"
            "2. 短语必须能在对应编号摘录中找到原文（可去掉标点差异）\n"
            "3. 不要输出：品牌/竞品公司名、客户名、地名、行业泛词"
            "（如「核心优势」「覆盖全国」）、问答套话（如「作为参考」「您的需求」）\n"
            "4. 不要输出仅罗列对比公司的短语\n"
            "5. 最多 20 条\n"
            '6. 严格输出 JSON：{"keywords":[{"text":"短语","index":1}]}\n'
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
        lead_analytics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """基于监测快照生成 GEO 报告结论与诊断建议。"""
        report_type_label = {
            "diagnosis": "企业诊断",
            "weekly": "监测周报",
            "monthly": "监测月报",
            "quarterly": "监测季报",
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
        from app.services.report_text_sanitize import consolidate_top_sources

        clean_sources = consolidate_top_sources(list(top_sources), limit=6)
        source_lines = [
            f"- {item.get('title') or item.get('url')}（{item.get('count')} 次）"
            for item in clean_sources
        ]
        prompt_lines: list[str] = []
        if lead_analytics:
            for row in lead_analytics.get("prompt_analytics") or []:
                prompt_lines.append(
                    f"- {row.get('prompt')}: 样本 {row.get('sample_count')}，"
                    f"品牌提及率 {row.get('brand_mention_rate')}%，"
                    f"平均排名 {row.get('brand_avg_rank') or '—'}"
                )
            source_note = (lead_analytics.get("source_analysis") or {}).get("coverage_note")
            if source_note:
                source_lines.append(f"- 信源覆盖：{source_note}")

        periodic_report = report_type in {"weekly", "monthly", "quarterly", "annual"}
        json_schema = (
            "{\n"
            '  "executive_summary": "120-220字执行摘要，含周期结论与1句行动方向",\n'
            '  "highlights": ["4-6条核心结论，每条25-60字"],\n'
            '  "sentiment_summary": "口碑与情绪总结，80-150字",\n'
            '  "strength_points": "优势亮点，2-4句",\n'
            '  "weakness_points": "待改善项，2-4句",\n'
            '  "recommendation": "可执行的 GEO 优化建议，分点叙述",\n'
            '  "health_score": 0-100 的整数'
        )
        if lead_analytics or periodic_report:
            section_hint = (
                "分语义词排名与竞品对比" if lead_analytics else "分平台排名与竞品对比"
            )
            html_hint = (
                '每项值为 HTML 片段（可含 <p> <strong style="color:#ff6666;"> 强调 <strong style="color:#66ccff;"> 次要），不要 markdown。'
                if lead_analytics
                else "每项值为纯文本"
            )
            json_schema += (
                ',\n'
                '  "report_sections": {\n'
                f'    "industry_analysis": "行业与 AI 搜索意图分析；输出 2~4 个独立短段（每段 40~90 字，可用多个 <p>），勿合成一段长文；{html_hint}",\n'
                f'    "ranking_analysis": "{section_hint}；输出 2~4 个独立短段（每段 40~90 字），覆盖短板语义词与竞品差距；{html_hint}",\n'
                f'    "mention_analysis": "提及率与曝光分析；输出 2~4 个独立短段（每段 40~90 字），覆盖整体与平台差异；{html_hint}",\n'
                f'    "source_analysis": "引用网站与信源覆盖；输出 2~4 个独立短段（每段 40~90 字）；{html_hint}",\n'
                f'    "action_recommendations": "分网站类型的优化建议列表，{html_hint}"\n'
                "  }"
            )
            if lead_analytics:
                json_schema += (
                    ',\n'
                    '  "analysis_html": "必填；五节解读 HTML（h2 为 1~5 节标题）。'
                    '第1~4节每节须输出 2~4 个独立 <p>（每段 40~90 字），从不同角度写短板/竞品/平台差异，禁止每节只写一大段；'
                    '第5节「采取措施建议」须含门户/垂直/问答/自媒体四类，每类下至少 2 条 li，'
                    '整节合计 8~10 条可执行建议（不得少于 8 条），勿输出【深度】【广度】等标签",\n'
                    '  "priority_actions": [{"priority":"P0|P1|P2","title":"行动项（40~80字，含对象+做法+场景，禁止写验收口径/承诺指标）","timeline":"30天|60天|90天"}],\n'
                    '  "prompt_commentaries": [{"prompt": "语义词原文", "comment": "80-120字 HTML 短评"}],\n'
                    '  "platform_insight": "分平台差异解读，100-150字",\n'
                    '  "source_action_tips": ["信源优化建议 10 条；每条 60~110 字；咨询顾问口吻；'
                    '说明「为何做+做什么+落到哪个站/问法」；禁止以「针对」开头；禁止验收口径/量化承诺"]'
                )
        json_schema += "\n}"

        system_prompt = (
            "你是 GEO（生成式引擎优化）监测报告撰写专家。"
            "请根据真实监测 KPI 与平台数据，输出面向客户交付的结构化报告结论。"
            "不得编造未提供的数据，不得虚构平台或指标。只输出 JSON，不要解释。"
        )
        if lead_analytics:
            system_prompt += (
                "售前诊断报告需对齐模力指数 HTML 报告："
                "analysis_html 使用 HTML，每节 h2 标题固定为"
                "「1. 行业分析」「2. 排名分析」「3. 提及率分析」「4. 引用网站分析」「5. 采取措施建议」，"
                "不要输出「数据分析与优化建议」总标题。"
                "重点 strong 红色(#ff6666)，补充 strong 蓝色(#66ccff)，节标题 h2 不要内联 style。"
                "前文诊断概览已展示 KPI，analysis_html 禁止重复具体 KPI 数字"
                "（如提及率%、Top3%、平均排名、样本数、信源数），改用「偏低/领先/落后竞品/差距明显」等定性表述。"
                "禁止引用异常/新闻杂讯类信源标题，用域名或网站类型描述。"
                "第1~4节每节必须拆成 2~4 条独立短段落（多个 <p>），不要每节一大段；"
                "第5节须用分类 ul/li 列出门户、垂直、问答、自媒体等网站类型建议，合计 8~10 条，每条写清动作与场景；不得少于 8 条。"
                "priority_actions 须 8~10 条，含 P0/P1/P2、timeline；title 40~80 字写清对象与动作；"
                "严禁出现「验收口径」「提升X%」「阅读量超过」等承诺式指标。"
                "source_action_tips 须恰好 10 条、每条 60~110 字：顾问口吻，说明原因+动作+落点站点/问法；"
                "严禁「针对」开头与空话套话；严禁验收口径。"
                "不要输出 analysis_action_tips，不要使用【深度】【广度】【维度】【策略】标签。"
            )
        prompt_section = ""
        if prompt_lines:
            prompt_section = "分语义词表现：\n" + "\n".join(prompt_lines) + "\n\n"
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
            f"{prompt_section}"
            "高频信源：\n"
            f"{chr(10).join(source_lines) or '- 暂无信源'}\n\n"
            "规则引擎初稿（可参考，勿照搬）：\n"
            f"{chr(10).join(f'- {line}' for line in rule_highlights) or '- 无'}\n\n"
            f"请输出 JSON：\n{json_schema}"
        )

        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=5600 if (lead_analytics or periodic_report) else 1800,
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

        report_sections = payload.get("report_sections")
        if not isinstance(report_sections, dict):
            report_sections = None
        else:
            report_sections = {
                key: str(report_sections.get(key) or "").strip()
                for key in (
                    "industry_analysis",
                    "ranking_analysis",
                    "mention_analysis",
                    "source_analysis",
                    "action_recommendations",
                )
                if str(report_sections.get(key) or "").strip()
            } or None

        prompt_commentaries = payload.get("prompt_commentaries")
        if not isinstance(prompt_commentaries, list):
            prompt_commentaries = None
        else:
            prompt_commentaries = [
                {
                    "prompt": str(item.get("prompt") or "").strip(),
                    "comment": str(item.get("comment") or "").strip(),
                }
                for item in prompt_commentaries
                if isinstance(item, dict) and str(item.get("prompt") or "").strip()
            ] or None

        source_action_tips = payload.get("source_action_tips")
        if not isinstance(source_action_tips, list):
            source_action_tips = None
        else:
            cleaned_tips: list[str] = []
            for item in source_action_tips:
                tip = str(item).strip()
                if not tip:
                    continue
                tip = re.sub(r"^针对\s*", "", tip)
                tip = re.sub(r"^【(?:深度|广度|维度|策略)】\s*", "", tip)
                tip = re.sub(r"验收口径[:：]?\s*", "", tip)
                # 去掉承诺式指标尾巴（提升X%、超过N）
                tip = re.sub(r"[，,；;].{0,24}(?:提升|达到|超过).{0,16}%[^。！？]*", "", tip)
                tip = tip.strip(" ：:;；")
                if tip and "验收口径" not in tip and tip not in cleaned_tips:
                    cleaned_tips.append(tip if tip.endswith(("。", "！", "？")) else tip + "。")
                if len(cleaned_tips) >= 12:
                    break
            source_action_tips = cleaned_tips or None

        priority_actions = payload.get("priority_actions")
        if not isinstance(priority_actions, list):
            priority_actions = None
        else:
            priority_actions = [
                {
                    "priority": str(item.get("priority") or "P2").upper(),
                    "title": re.sub(
                        r"(验收口径|提升\s*\d+%|超过\s*\d+)",
                        "",
                        str(item.get("title") or "").strip(),
                    ).strip(" ：:;；"),
                    "timeline": str(item.get("timeline") or "90天").strip(),
                }
                for item in priority_actions
                if isinstance(item, dict) and str(item.get("title") or "").strip()
            ][:8] or None

        return {
            "executive_summary": _text("executive_summary"),
            "highlights": highlights,
            "sentiment_summary": _text("sentiment_summary"),
            "strength_points": _text("strength_points"),
            "weakness_points": _text("weakness_points"),
            "recommendation": _text("recommendation"),
            "health_score": health_score,
            "report_sections": report_sections,
            "analysis_html": _text("analysis_html"),
            "prompt_commentaries": prompt_commentaries,
            "platform_insight": _text("platform_insight"),
            "source_action_tips": source_action_tips,
            "priority_actions": priority_actions,
        }

    def generate_source_value_analyses(
        self,
        *,
        brand_name: str,
        period_label: str,
        sources: list[dict[str, Any]],
    ) -> list[str]:
        """根据信源正文摘录批量生成「渠道价值拆解」；禁止无正文编造细节。"""
        # 2026-07-29 - 渠道价值拆解敷衍同句 - 按链接正文写「定性+GEO价值+一条动作」
        cleaned: list[dict[str, Any]] = []
        for index, raw in enumerate(sources[:8], start=1):
            title = str((raw or {}).get("title") or (raw or {}).get("url") or "").strip()
            excerpt = re.sub(r"\s+", " ", str((raw or {}).get("excerpt") or "").strip())
            if not title or not excerpt:
                continue
            platforms = (raw or {}).get("platforms") or []
            if isinstance(platforms, (list, tuple, set)):
                plat_text = "、".join(str(p).strip() for p in platforms if str(p).strip())
            else:
                plat_text = str(platforms or "").strip()
            cleaned.append(
                {
                    "index": index,
                    "title": title[:180],
                    "url": str((raw or {}).get("url") or "").strip()[:240],
                    "count": int((raw or {}).get("count") or 0),
                    "platforms": plat_text or "—",
                    "excerpt": excerpt[:3200],
                }
            )
        if not cleaned:
            return []
        if not self.report_enabled:
            raise DeepseekApiError("未开启 deepseek_report_enabled")

        blocks = []
        for row in cleaned:
            blocks.append(
                f"[{row['index']}] 标题={row['title']}\n"
                f"url={row['url'] or '—'}\n"
                f"引用次数={row['count']}；出现平台={row['platforms']}\n"
                f"正文摘录：\n{row['excerpt']}"
            )
        system_prompt = (
            "你是 GEO（生成式引擎优化）信源顾问。必须依据「正文摘录」评价该文章/页面对品牌 AI 引用的价值。"
            "每条 value_analysis 用 40~90 字写满三要素："
            "①内容定性（主题/场景/体裁）；②对 AI 引用或选型决策的价值；③一条可执行建议。"
            "禁止「累计引用 N 次的高权重渠道…」万能套话；禁止编造摘录未出现的数据/合作事实。"
            "只输出 JSON。"
        )
        user_prompt = (
            f"品牌：{brand_name or '—'}\n"
            f"周期：{period_label or '—'}\n\n"
            "信源材料：\n\n"
            f"{chr(10).join(blocks)}\n\n"
            "请输出 JSON：\n"
            "{\n"
            '  "items": [\n'
            '    {"index": 1, "value_analysis": "40~90字，含定性+GEO价值+一条动作"}\n'
            "  ]\n"
            "}\n"
            f"要求：items 恰好 {len(cleaned)} 条，index 与输入一一对应；纯中文，勿 markdown。"
        )
        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.35,
            max_tokens=1800,
            source="source-value-analysis",
        )
        payload = self._parse_json_payload(content)
        if not isinstance(payload, dict):
            raise DeepseekApiError("信源价值拆解 JSON 格式错误")
        items = payload.get("items")
        if not isinstance(items, list):
            raise DeepseekApiError("信源价值拆解缺少 items")

        by_index: dict[int, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            text = re.sub(r"\s+", " ", str(item.get("value_analysis") or "").strip())
            if not text:
                continue
            if "累计引用" in text and "高权重渠道" in text:
                continue
            if len(text) > 120:
                text = text[:119].rstrip("，,；; ") + "…"
            if not text.endswith(("。", "！", "？", "…")):
                text += "。"
            by_index[idx] = text

        out: list[str] = []
        for row in cleaned:
            text = by_index.get(int(row["index"]))
            if not text:
                raise DeepseekApiError(f"信源价值拆解缺少 index={row['index']}")
            out.append(text)
        if len(out) >= 3 and len({t[:18] for t in out}) <= 1:
            raise DeepseekApiError("信源价值拆解同质化过高")
        return out

    def resolve_domain_site_labels(
        self,
        items: list[dict[str, Any]],
    ) -> dict[str, str]:
        """从候选站名中选择汉字发布方名；无把握则省略该键。禁止发明候选外名称。"""
        cleaned: list[dict[str, Any]] = []
        for raw in items[:40]:
            host = str((raw or {}).get("domain") or "").strip().lower()
            if not host:
                continue
            cands = []
            seen: set[str] = set()
            for c in list((raw or {}).get("candidates") or []):
                text = str(c or "").strip()
                if not text or text.lower() == host or text in seen:
                    continue
                seen.add(text)
                cands.append(text)
            titles = [str(t).strip() for t in list((raw or {}).get("titles") or []) if str(t).strip()][:3]
            if not cands and not titles:
                continue
            cleaned.append(
                {
                    "domain": host,
                    "candidates": cands[:8],
                    "titles": titles,
                    "brand": str((raw or {}).get("brand") or "").strip(),
                }
            )
        if not cleaned or not self.report_enabled:
            return {}

        blocks = []
        for row in cleaned:
            blocks.append(
                f"域名: {row['domain']}\n"
                f"候选站名: {json.dumps(row['candidates'], ensure_ascii=False)}\n"
                f"引用标题样例: {json.dumps(row['titles'], ensure_ascii=False)}\n"
                f"客户品牌(禁止当作站名): {row['brand'] or '—'}"
            )
        content = self.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是中文信源站名校对助手。任务是从「候选站名」里选出最像第三方发布方/媒体的汉字站名。"
                        "硬性规则：\n"
                        "1) 只能输出候选列表中的某一项原文，禁止改写、禁止发明候选外名称；\n"
                        "2) 若候选都不像独立站名、或只是客户品牌/公司主体、或全是英文域名碎片，省略该域名；\n"
                        "3) 只输出 JSON 对象：键=域名，值=选中的候选原文；无把握的键不要出现。\n"
                        "标题仅作辅助判断，不能当站名输出（除非它也出现在候选里）。"
                    ),
                },
                {
                    "role": "user",
                    "content": "请处理：\n\n"
                    + "\n\n".join(blocks)
                    + '\n\n只输出 JSON，例如 {"jobui.com":"职友集"}',
                },
            ],
            temperature=0.0,
            max_tokens=800,
            source="site-label",
        )
        payload = self._parse_json_payload(content)
        if not isinstance(payload, dict):
            return {}
        allowed = {row["domain"]: set(row["candidates"]) for row in cleaned}
        out: dict[str, str] = {}
        for key, value in payload.items():
            host = str(key or "").strip().lower()
            label = str(value or "").strip()
            if not host or not label:
                continue
            if label not in allowed.get(host, set()):
                continue
            out[host] = label
        return out

    def parse_knowledge_document(
        self,
        *,
        brand_name: str,
        company_name: str | None,
        file_name: str,
        document_text: str,
        truncated: bool,
    ) -> dict[str, Any]:
        """Extract structured preview sections from enterprise knowledge text."""
        system_prompt = (
            "你是 GEO 企业知识库分析助手。请阅读企业上传的资料文本，"
            "按资料实际结构提炼可预览的内容块。标题必须来自资料本身（如章节名、业务名、产品名），"
            "禁止编造资料中不存在的信息，禁止输出固定占位标题。只输出 JSON，不要解释。"
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
            '  "sections": [\n'
            '    {"title": "从资料提炼的小节标题", "type": "text", "content": "该小节完整段落"},\n'
            '    {"title": "从资料提炼的小节标题", "type": "list", "items": ["条目1", "条目2"]},\n'
            '    {"title": "从资料提炼的小节标题", "type": "cards", "items": [{"title":"子标题","content":"说明"}]}\n'
            "  ]\n"
            "}\n"
            "要求：sections 至少 2 项；title 必须贴合资料语义；type 只能是 text/list/cards。"
        )
        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=3200,
            source="knowledge-parse",
        )
        payload = self._parse_json_payload(content)
        if not isinstance(payload, dict):
            raise DeepseekApiError("DeepSeek 知识库 JSON 格式错误")

        sections = self._normalize_knowledge_sections(payload.get("sections"))
        if not sections:
            raise DeepseekApiError("DeepSeek 未返回可预览的内容块")

        return {
            "source": "deepseek",
            "model": self.model,
            "sections": sections,
        }

    def extract_brand_rank_from_answer(
        self,
        *,
        brand_terms: list[str],
        monitor_keyword: str,
        prompt: str,
        answer_text: str,
        truncated: bool = False,
    ) -> dict[str, Any]:
        """Extract brand list rank from a monitor answer using ranking rules."""
        aliases = "、".join(term.strip() for term in brand_terms if str(term or "").strip())
        truncate_note = "（正文已截断）" if truncated else ""
        system_prompt = (
            "你是 GEO 品牌监测排名分析助手。请根据 AI 回答正文，判断目标品牌在「与监测词最相关的小节/表格」中的推荐位次。"
            "排名规则：\n"
            "1. 优先看与监测词/问题语义最匹配的 ##/### 小节或表格；在该小节内按 1. 2. 3. 或表格行序计数。\n"
            "2. 若存在 Markdown 表格且含企业名列，按表格行序排名。\n"
            "3. 品牌未出现在任何推荐列表/表格中则 brand_mentioned=false、rank=null。\n"
            "4. 不要把全篇第一次出现的段落序号当作排名；不要跨小节累计。\n"
            # 2026-07-29 - 选型表「首选」第一行被判成备选第4 - 明确首选列优先于备选/补充表
            "5. 表格若有「首选推荐/首选」与「备选」列：品牌在首选列出现时，以该表中首次作为首选的数据行序为 rank；"
            "仅在备选列出现才用备选行序。优先「选型建议/场景推荐」主表，不要用「其他补充」或回答前的思考过程压过主表。\n"
            "6. 只输出 JSON，不要解释。"
        )
        user_prompt = (
            f"监测词：{monitor_keyword}\n"
            f"问题：{prompt}\n"
            f"目标品牌及别名：{aliases}\n"
            f"{truncate_note}\n\n"
            "回答正文：\n"
            f"{answer_text}\n\n"
            "输出 JSON：\n"
            "{\n"
            '  "brand_mentioned": true,\n'
            '  "rank": 4,\n'
            '  "category": "区域优质工程商",\n'
            '  "rank_basis": "section_list",\n'
            '  "confidence": 0.92,\n'
            '  "evidence": "引用原文中品牌所在列表行（不超过80字）"\n'
            "}\n"
            "rank_basis 取值：section_list | section_bullet | markdown_table | prose | none\n"
            "confidence 范围 0~1。"
        )
        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=512,
            source="rank_fallback",
        )
        payload = self._parse_json_payload(content)
        if not isinstance(payload, dict):
            raise DeepseekApiError("DeepSeek 排名解析返回不是 JSON 对象")
        return payload

    @staticmethod
    def _normalize_knowledge_sections(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        sections: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            section_type = str(item.get("type") or "text").strip().lower()
            if not title:
                continue
            if section_type == "list":
                items = [str(v).strip() for v in (item.get("items") or []) if str(v).strip()]
                if items:
                    sections.append({"title": title, "type": "list", "items": items})
                continue
            if section_type == "cards":
                cards: list[dict[str, str]] = []
                for card in item.get("items") or []:
                    if not isinstance(card, dict):
                        continue
                    card_title = str(card.get("title") or "").strip()
                    card_content = str(card.get("content") or "").strip()
                    if card_title or card_content:
                        cards.append({"title": card_title, "content": card_content})
                if cards:
                    sections.append({"title": title, "type": "cards", "items": cards})
                continue
            content_text = str(item.get("content") or "").strip()
            if content_text:
                sections.append({"title": title, "type": "text", "content": content_text})
        return sections[:12]
