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

    @property
    def rank_fallback_enabled(self) -> bool:
        return bool(self.api_key) and settings.deepseek_rank_fallback_enabled

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise DeepseekApiError("未配置 DEEPSEEK_API_KEY")
        return {
            "Authorization": f"Bearer {self.api_key}",
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
                f'    "industry_analysis": "行业与 AI 搜索意图分析，120-200字，{html_hint}",\n'
                f'    "ranking_analysis": "{section_hint}，120-200字，{html_hint}",\n'
                f'    "mention_analysis": "提及率与曝光分析，100-180字，{html_hint}",\n'
                f'    "source_analysis": "引用网站与信源覆盖，100-180字，{html_hint}",\n'
                f'    "action_recommendations": "分网站类型的优化建议列表，{html_hint}"\n'
                "  }"
            )
            if lead_analytics:
                json_schema += (
                    ',\n'
                    '  "analysis_html": "可选；五节解读 HTML（h2 为 1~5 节标题，第5节含分类 ul/li），勿重复概览 KPI",\n'
                    '  "priority_actions": [{"priority":"P0|P1|P2","title":"行动项","timeline":"30天|60天|90天"}],\n'
                    '  "prompt_commentaries": [{"prompt": "语义词原文", "comment": "80-120字 HTML 短评"}],\n'
                    '  "platform_insight": "分平台差异解读，100-150字",\n'
                    '  "source_action_tips": ["按信源类型的优化建议，3-5条"]'
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
                "第5节须用分类 ul/li 列出门户、垂直、问答、自媒体等网站类型建议。"
                "priority_actions 须 3~5 条，与第5节方向一致但更具体，含 P0/P1/P2 与 timeline。"
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
            temperature=0.25,
            max_tokens=4096 if (lead_analytics or periodic_report) else 1800,
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
            source_action_tips = [str(item).strip() for item in source_action_tips if str(item).strip()][:5] or None

        priority_actions = payload.get("priority_actions")
        if not isinstance(priority_actions, list):
            priority_actions = None
        else:
            priority_actions = [
                {
                    "priority": str(item.get("priority") or "P2").upper(),
                    "title": str(item.get("title") or "").strip(),
                    "timeline": str(item.get("timeline") or "90天").strip(),
                }
                for item in priority_actions
                if isinstance(item, dict) and str(item.get("title") or "").strip()
            ][:5] or None

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
            "5. 只输出 JSON，不要解释。"
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
