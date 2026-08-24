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

_STAGE_KEYS = ("all", "recognition", "selection", "procurement", "risk")
_STAGE_LABELS = {
    # 2026-08-20 - 与顶栏/桌面 G 一致：竞品对标，不再写技术选型
    "all": "管理层摘要",
    "recognition": "品牌认知",
    "selection": "竞品对标",
    "procurement": "推荐名单",
    "risk": "口碑评价",
}
_PRIORITY_DEFAULTS = (
    ("p0", "P0 · 场景攻坚", "status-risk", "缺口明显"),
    ("p1", "P1 · 平台覆盖", "status-gap", "需结构化"),
    ("p2", "P2 · 优势放大", "status-ok", "基础较强"),
)
_ACTION_DEFAULTS = (
    ("p0", "P0 · 30 天", "夯实决策底稿"),
    ("p1", "P1 · 60 天", "提升前三占比"),
    ("p2", "P2 · 90 天", "扩大权威引用"),
)


def _normalize_cockpit_narrative(payload: dict[str, Any], *, brand: str) -> dict[str, Any]:
    """收敛驾驶舱叙事 JSON，保证壳字段齐全。"""
    stage_in = payload.get("stage_copy") if isinstance(payload.get("stage_copy"), dict) else {}
    stage_copy: dict[str, dict[str, str]] = {}
    for key in _STAGE_KEYS:
        row = stage_in.get(key) if isinstance(stage_in.get(key), dict) else {}
        title = str(row.get("title") or "").strip() or f"{brand} AI 可见度仍有提升空间"
        if "<span>" not in title:
            title = f"{title}<span>明确推荐位</span>" if key == "all" else title
        stage_copy[key] = {
            "label": str(row.get("label") or _STAGE_LABELS[key]).strip() or _STAGE_LABELS[key],
            "title": title,
            "summary": str(row.get("summary") or "").strip() or f"{brand} 监测窗口内的可见度判断。",
        }

    raw_priority = payload.get("priority_items") if isinstance(payload.get("priority_items"), list) else []
    priority_items: list[dict[str, str]] = []
    for idx, defaults in enumerate(_PRIORITY_DEFAULTS):
        level_class, level, tone, tone_label = defaults
        row = raw_priority[idx] if idx < len(raw_priority) and isinstance(raw_priority[idx], dict) else {}
        priority_items.append(
            {
                "level_class": level_class,
                "level": str(row.get("level") or level).strip() or level,
                "tone": str(row.get("tone") or tone).strip() or tone,
                "tone_label": str(row.get("tone_label") or tone_label).strip() or tone_label,
                "title": str(row.get("title") or f"{level_class.upper()} 行动").strip(),
                "body": str(row.get("body") or "基于监测短板给出的优先动作。").strip(),
            }
        )

    raw_risks = payload.get("risk_rows") if isinstance(payload.get("risk_rows"), list) else []
    risk_rows: list[dict[str, str]] = []
    for item in raw_risks[:5]:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        priority = str(item.get("priority") or "P1").strip().upper()
        if priority not in {"P0", "P1", "P2"}:
            priority = "P1"
        risk_rows.append(
            {
                "topic": topic,
                "models": str(item.get("models") or "多平台").strip() or "多平台",
                "impact": str(item.get("impact") or "影响入围").strip() or "影响入围",
                "evidence": str(item.get("evidence") or "案例与权威信源").strip() or "案例与权威信源",
                "priority": priority,
                "pill": "risk-high" if priority == "P0" else "risk-medium",
            }
        )
    if len(risk_rows) < 3:
        for item in priority_items:
            risk_rows.append(
                {
                    "topic": item["title"],
                    "models": "已监测平台",
                    "impact": "影响入围与推荐位" if item["level_class"] == "p0" else "影响说服力",
                    # 2026-08-13 - 禁止空泛「案例与权威信源」；证据必须来自优先项正文
                    "evidence": item["body"],
                    "priority": item["level"].split("·", 1)[0].strip() or "P1",
                    "pill": "risk-high" if item["level_class"] == "p0" else "risk-medium",
                }
            )
            if len(risk_rows) >= 4:
                break

    raw_actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    actions: list[dict[str, Any]] = []
    for idx, defaults in enumerate(_ACTION_DEFAULTS):
        level_class, level, impact = defaults
        row = raw_actions[idx] if idx < len(raw_actions) and isinstance(raw_actions[idx], dict) else {}
        bullets_raw = row.get("bullets") if isinstance(row.get("bullets"), list) else []
        bullets = [str(x).strip() for x in bullets_raw if str(x).strip()][:5]
        base = priority_items[idx] if idx < len(priority_items) else {}
        if len(bullets) < 3:
            bullets = [
                f"要解决的问法/问题：{base.get('title') or '监测短板'}",
                f"数据证据：{str(base.get('body') or '暂无数据')[:80]}",
                "复测方式：同问法×已监测平台复跑，对比获客提及率/均排/Top3",
            ]
        actions.append(
            {
                "level_class": level_class,
                "level": str(row.get("level") or level).strip() or level,
                "impact": str(row.get("impact") or impact).strip() or impact,
                "title": str(row.get("title") or base.get("title") or level).strip(),
                "body": str(row.get("body") or base.get("body") or "按阶段推进内容与信源建设。").strip(),
                "bullets": bullets,
            }
        )

    # 2026-08-21 - 生成后 scrub：客户可见禁「选型标准/选型路径」品类，对齐换皮版-G
    def _scrub(s: str) -> str:
        text = str(s or "")
        for old, new in (
            ("选型标准问法", "推荐类问法"),
            ("选型路径问法", "推荐类问法"),
            ("选择标准类问法", "推荐类问法"),
            ("选择标准问法", "推荐类问法"),
            ("选型标准意图", "推荐意图"),
            ("选型路径意图", "推荐意图"),
            ("选型标准", "推荐名单"),
            ("选型路径", "推荐名单"),
            ("选择标准", "推荐名单"),
            ("竞品对比", "竞品对标"),
            ("技术选型", "竞品对标"),
        ):
            text = text.replace(old, new)
        return text

    for key, row in stage_copy.items():
        stage_copy[key] = {
            "label": _scrub(row["label"]) if key != "selection" else _STAGE_LABELS["selection"],
            "title": _scrub(row["title"]),
            "summary": _scrub(row["summary"]),
        }
        if key == "selection" and any(
            tok in f"{row.get('title')}{row.get('summary')}" for tok in ("选型标准", "技术选型", "选型类问题")
        ):
            stage_copy[key] = {
                "label": _STAGE_LABELS["selection"],
                "title": f"{brand}非品牌词获客里要<span>盯紧竞品同框</span>",
                "summary": f"对照竞品在非品牌词回答中的共现与位次，判断{brand}是否被挤出同框。",
            }
    for item in priority_items:
        item["title"] = _scrub(item["title"])
        item["body"] = _scrub(item["body"])
        item["level"] = _scrub(item["level"])
        item["tone_label"] = _scrub(item["tone_label"])
    for item in risk_rows:
        for field in ("topic", "models", "impact", "evidence"):
            item[field] = _scrub(item[field])
    for item in actions:
        item["title"] = _scrub(item["title"])
        item["body"] = _scrub(item["body"])
        item["impact"] = _scrub(item["impact"])
        item["bullets"] = [_scrub(x) for x in item["bullets"]]

    return {
        "stage_copy": stage_copy,
        "priority_items": priority_items,
        "risk_rows": risk_rows[:5],
        "actions": actions,
        "source": "deepseek",
    }


# 改 prompt 时跑 tests/test_rank_prompt_contract.py，确保硬约束未丢
RANK_PROMPT_CONTRACT_MARKERS: tuple[str, ...] = (
    "计位优先级",
    "禁止跨档",
    "计位范围锁定",
    "地理分区",
    "ordered_brands",
    "首选/备选",
    "需求→推荐品牌",
    "rank_basis=prose",
    "category_ranks",
    "城市名",
    "brand_mentioned=false",
    "section_list",
    "section_bullet",
    "markdown_table",
)


def _build_brand_rank_prompts(
    *,
    monitor_keyword: str,
    prompt: str,
    aliases: str,
    answer_text: str,
    truncate_note: str,
) -> tuple[str, str]:
    """排名 LLM 提示词（system + user）。语义与 2026-08-24 口径一致，去重复案例。"""
    system_prompt = (
        "你是 GEO 品牌监测排名分析助手。根据 AI「正式回答」正文，判断目标品牌的位次。"
        "计位优先级（严格按序，只选一层）：\n"
        "A. 有分类/分档（进口/国产、一手资源/整合代理、一线/二梯队等 ##/###）→ "
        "仅在目标所在档内按行序计位，category 抄该档标题；禁止跨档累加。\n"
        "B. 无分档但有品牌对比表/编号推荐列表 → 按表数据行或列表项顺序计位。\n"
        "C. 以上都没有 → 全文出场序：按品牌样实体出现先后计位（含选择建议、决策清单、顺口提及），"
        "rank_basis=prose；禁止因「只是顺口提到」报 rank=null。\n"
        "硬性规则：\n"
        "1. 只看正式回答；忽略思考过程、搜索结果、网页标题、引用角标、页眉品牌名。\n"
        "2. 【计位范围锁定】走 A 时 ordered_brands 只写目标所在最小独立分组（档/小节/城市子组）"
        "内的主列表项（编号或 bullet），禁止跨档、跨小节、跨城市子组合并累加；"
        "地理分区/市场集散地等标题只划定范围，本身不占 rank、不得当 rank1。"
        "反例：进口3家+国产第4个目标 → rank=4 非 7；二档第1个整合商 → rank=1 非前两档累加；"
        "「单城官方」8家+「全国联动」第4个目标 → rank=4、ordered_brands 仅该档5项，非 12。\n"
        "3. 主推荐表优先于特色视角/备选/补充段；若输出 category_ranks，矩阵取主表最靠前一条。\n"
        "4. 表格按数据行序（表头不算）；有首选/备选列时首选列优先，仅备选列出现才用备选行序；"
        "选择建议表按「需求→推荐品牌」列出场序。\n"
        "5. 先写 ordered_brands（至少前8个，不足全写），rank=目标在其中的 1-based 下标，二者必须一致；"
        "C 时 ordered_brands 为全文品牌实体去重保序。\n"
        "6. category：A/B 抄小节或表标题；C 可写「全文出场」或所在小节标题。\n"
        "7. 正文完全未出现目标及别名 → brand_mentioned=false、rank=null、ordered_brands=[]；"
        "只要出现过 → brand_mentioned=true 且必须给出 rank。\n"
        "8. 城市名（北京/上海/广州等）不是品牌，不得计入 ordered_brands。\n"
        "9. 只输出 JSON，不要解释。"
    )
    user_prompt = (
        f"监测词：{monitor_keyword}\n"
        f"问题：{prompt}\n"
        f"目标品牌及别名：{aliases}\n"
        f"{truncate_note}\n\n"
        "回答正文：\n"
        f"{answer_text}\n\n"
        "按 system 规则 A→B→C 判断；先写 ordered_brands 再定 rank。仅输出 JSON：\n"
        "{\n"
        '  "brand_mentioned": true,\n'
        '  "ordered_brands": ["品牌A", "品牌B"],\n'
        '  "rank": 2,\n'
        '  "category": "小节或表标题",\n'
        '  "rank_basis": "section_list|section_bullet|markdown_table|prose|none",\n'
        '  "confidence": 0.92,\n'
        '  "evidence": "原文片段≤80字"\n'
        "}"
    )
    return system_prompt, user_prompt


def _build_brand_rank_prompts_legacy(
    *,
    monitor_keyword: str,
    prompt: str,
    aliases: str,
    answer_text: str,
    truncate_note: str,
) -> tuple[str, str]:
    """2026-08-24 瘦身前快照，仅审计脚本对比用。"""
    system_prompt = (
        "你是 GEO 品牌监测排名分析助手。请根据 AI「正式回答」正文，判断目标品牌的位次。"
        "计位优先级（必须按此顺序，只能选一层）：\n"
        "A. 有分类/分档（如进口/国产、一手资源/整合代理、一线/二梯队等 ##/### 小节）→ "
        "只在目标品牌所在那一档内按行序计位，category 抄该档标题；禁止跨档累加。\n"
        "B. 无可用分类位次、但有品牌对比表/编号推荐列表 → 按表数据行或列表项顺序计位。\n"
        "C. 以上都没有 → 全文出场序：在正式回答中按「品牌样实体」出现先后，"
        "目标品牌是第几个就 rank=几（含选择建议、决策清单、顺口点名等散文提及）；"
        "rank_basis=prose。禁止因为「只是顺口提到」就报 rank=null。\n"
        "排名细则：\n"
        "1. 只看正式回答；忽略思考过程、搜索结果、网页标题、引用角标、"
        "Shared Conversation 页眉里的品牌名。\n"
        "2. 【分档硬规则】走 A 时：ordered_brands 只能写目标所在那一档的品牌。"
        "错误示例：进口档已有3家，国产档第4个是目标 → 正确 rank=4；禁止 rank=7（3+4）。"
        "又例：一档4家核心资源方 + 二档第1个整合服务商 → 正确 rank=1（二档内），禁止 rank=5。\n"
        "3. 主推荐表与「特色视角/备选/补充」同时有目标品牌时，优先主表（A/B），不要改用次要段。\n"
        "4. 表格含品牌列时按数据行序（表头不算）；有「首选/备选」列时：首选列出现用首选行序，"
        "仅在备选列出现才用备选行序。选择建议表若有「需求→推荐品牌」列，按推荐列品牌出现序。\n"
        "5. 必须先写出本次计位所用序列 ordered_brands（至少前 8 个，不足则全写），"
        "再把目标品牌在该数组中的 1-based 下标作为 rank；rank 必须与 ordered_brands 一致。"
        "走 C 全文时，ordered_brands 为全文中依次出现的品牌样实体（去重保序）。\n"
        "6. category：走 A/B 时抄原文小节/表格标题；走 C 时可写「全文出场」或所在小节标题。\n"
        "7. 正文完全未出现目标品牌及别名 → brand_mentioned=false、rank=null、ordered_brands=[]。"
        "只要出现过（含顺口提），brand_mentioned=true 且必须给出 rank（走 A/B/C 之一）。\n"
        "8. 不要跨小节累计；不要把思考过程里的点名当作家。\n"
        "9. 若输出 category_ranks：每个正式分类各给一条；矩阵最终取主表中最靠前的一条，"
        "次要段不要压过主表。\n"
        "10. 【城市分组禁止累加】一档内按城市分子组（如「**北京**：公司A；公司B」「**上海**：…」）时，"
        "ordered_brands 只写目标所在那一档的主列表项（编号/bullet），不要把各城市子列表首尾相接。"
        "例：「一、单城官方」下列 8 家 +「二、全国多城联动」第 4 个是目标 → rank=4、"
        "ordered_brands 仅含该档 5 项，禁止 rank=12（8+4）。\n"
        "11. 城市名（北京/上海/广州等）不是品牌，不得计入 ordered_brands。\n"
        "12. 只输出 JSON，不要解释。"
    )
    user_prompt = (
        f"监测词：{monitor_keyword}\n"
        f"问题：{prompt}\n"
        f"目标品牌及别名：{aliases}\n"
        f"{truncate_note}\n\n"
        "回答正文：\n"
        f"{answer_text}\n\n"
        "提醒：先判断走 A 分类 / B 表列表 / C 全文；"
        "分档时若正文有「## 进口 … 1.A 2.B 3.C」和「## 国产 … 1.D 2.E 3.目标 4.F」，"
        "目标在国产档 → ordered_brands 只能类似 [\"D\",\"E\",\"目标\",\"F\"]，rank=3，"
        "禁止混入进口档或 rank=6。\n"
        "地铁/公交例：「一、单城官方」按城市列公司 +「二、全国多城联动」bullet 列表，"
        "目标在第二节第 4 条 → rank=4，category 抄「全国多城联动」，"
        "ordered_brands 只写第二节 5 个品牌，禁止把第一节各城市公司累加成 8 再 +4。\n\n"
        "输出 JSON：\n"
        "{\n"
        '  "brand_mentioned": true,\n'
        '  "ordered_brands": ["品牌A", "品牌B", "品牌C"],\n'
        '  "rank": 3,\n'
        '  "category": "热门品牌速览",\n'
        '  "rank_basis": "markdown_table",\n'
        '  "confidence": 0.92,\n'
        '  "evidence": "引用原文中品牌所在列表行（不超过80字）"\n'
        "}\n"
        "rank_basis 取值：section_list | section_bullet | markdown_table | prose | none\n"
        "confidence 范围 0~1。\n"
        "自检：①目标是 ordered_brands 第 k 个则 rank=k；"
        "②走 A 时 ordered_brands 未混入其他档；③有露出则 rank 不得为 null。"
    )
    return system_prompt, user_prompt


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

        # 2026-07-31 - S3：强制短语自身极性，禁止把中性卖点塞进负面词云
        system_prompt = (
            "你是 GEO 品牌监测分析助手。请从品牌邻近摘录中提取短语，"
            "每个短语本身必须带有指定情感倾向，用于正负面词云。只输出 JSON，不要解释。"
        )
        user_prompt = (
            f"品牌：{brand_name}\n"
            f"目标情感：{polarity_label}\n\n"
            f"{exclude_block}"
            "摘录（多为品牌名邻近窗口，非全文）：\n"
            f"{chr(10).join(lines)}\n\n"
            "要求：\n"
            f"1. 只提取短语本身明确表达「{polarity_label}」的评价（如风险/短板/坑点，或优势/靠谱/推荐），"
            "4-16 个汉字为宜\n"
            "2. 短语必须能在对应编号摘录中找到原文（可去掉标点差异）\n"
            "3. 严禁输出中性事实/资源描述（如「一手资源」「全国覆盖」「地铁广告」），"
            "即使出现在负面回答里也不要输出\n"
            "4. 不要输出：品牌/竞品公司名、客户名、地名、行业泛词、问答套话\n"
            "5. 不要输出仅罗列对比公司的短语\n"
            "6. 最多 20 条；没有符合极性的短语时返回空数组\n"
            '7. 严格输出 JSON：{"keywords":[{"text":"短语","index":1}]}\n'
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
                    '  "analysis_html": "必填；HTML（不要输出「数据分析与优化建议」总标题）。'
                    '结构固定三块：'
                    '① <h2>分析结论</h2> 下 6~8 个独立 <p>（每发现一段，禁止合成超长单段），'
                    '覆盖最强/最弱场景词差距、平台覆盖不均、Top3、信源多样性、竞品对照；'
                    '定性词后必须紧跟具体数字；'
                    '重点 <strong style=\\"color:#ff6666;\\">，补充动作 <strong style=\\"color:#66ccff;\\">，h2/h3 不要内联 style；'
                    '② <h2>攻坚优先级</h2> 下用 <h3>P0</h3>/<h3>P1</h3>/<h3>P2</h3> + <ul><li>：'
                    'P0 被竞品压制场景/平台（对比数字+双线动作+目标），'
                    'P1 差距约≤20pt 可追场景，P2 持平防守+信源结构升级；'
                    '③ <h2>渠道路径</h2> 按问答平台/垂直媒体/门户/自媒体/权威背书五类汇总动作，注明以合规口径执行。'
                    '量化目标统一写「首要目标：争取将提及率提到约 A%～B%」（均排写「争取将均排提到约 X 以内」）；'
                    '禁止「30天内提升至X%」「60天目标Y%」「验收口径」等合同式承诺；'
                    '情感计数以输入为准，合计>0 时禁止写均为0/无情绪数据",\n'
                    '  "priority_actions": [{"priority":"P0|P1|P2","title":"行动项（40~80字，对象+做法+场景；可用首要目标区间表述，禁止验收口径/死日期单点承诺）","timeline":"30天|60天|90天"}],\n'
                    '  "prompt_commentaries": [{"prompt": "语义词原文", "comment": "80-120字 HTML 短评"}],\n'
                    '  "platform_insight": "分平台差异解读，100-150字",\n'
                    '  "source_action_tips": ["信源优化建议 8~10 条纯文本（禁止 HTML 标签）；'
                    '每条以「具体域名+引用次数」开篇；2~3 句可执行；'
                    '覆盖官网/问答/百科/垂直/门户/社媒/文档/监测；挂钩短板语义词；'
                    '禁止以「针对」开头；禁止验收口径"]'
                )
        json_schema += "\n}"

        system_prompt = (
            "你是 GEO（生成式引擎优化）监测报告撰写专家。"
            "请根据真实监测 KPI 与平台数据，输出面向客户交付的结构化报告结论。"
            "不得编造未提供的数据，不得虚构平台或指标。只输出 JSON，不要解释。"
        )
        if lead_analytics:
            # 2026-08-04 - 售前诊断改用三块结构（分析结论/攻坚优先级/渠道路径），替换旧 1~5 节口径
            system_prompt += (
                "售前诊断报告需对齐模力指数 HTML 报告。"
                "analysis_html 使用 HTML，结构固定为："
                "「分析结论」→「攻坚优先级（P0/P1/P2）」→「渠道路径」三块 h2；"
                "不要输出「数据分析与优化建议」总标题，也不要再用「1.行业分析…5.采取措施建议」旧五节标题。"
                "分析结论：6~8 个发现，每个独立 <p>，禁止超长单段；"
                "短板/领先/覆盖不足等定性后必须跟具体数字。"
                "攻坚优先级：h3 为 P0/P1/P2，下列 ul/li；含竞品对比数字、双线动作与首要目标区间。"
                "渠道路径：按问答平台/垂直媒体/门户/自媒体/权威背书五类写动作，注明以合规口径执行。"
                "重点 strong 红色(#ff6666)，补充动作/站点 strong 蓝色(#66ccff)，节标题 h2/h3 不要内联 style。"
                "禁止引用异常/新闻杂讯类信源标题，用域名或网站类型描述。"
                "priority_actions 须 6~10 条，含 P0/P1/P2、timeline；title 40~80 字写清对象与动作；"
                "量化目标统一「首要目标：争取将提及率提到约 A%～B%」或均排「约 X 以内」；"
                "严禁「验收口径」「30天内提升至X%」「60天目标Y%」等合同式承诺。"
                "source_action_tips 须 8~10 条纯文本（禁止 HTML）：以域名+引用次数开篇；"
                "顾问口吻说明原因+动作+落点；挂钩短板语义词；严禁「针对」开头与验收口径。"
                "情感正/中/负以输入计数为准，合计>0 时禁止写均为0/无情绪数据。"
                "不要输出 analysis_action_tips，不要使用【深度】【广度】【维度】【策略】标签。"
            )
        prompt_section = ""
        if prompt_lines:
            prompt_section = "分语义词表现：\n" + "\n".join(prompt_lines) + "\n\n"
        # 2026-08-14 - 情绪占比分母=全部完成样本（含未知），禁止只用已标注算出虚高 80%
        from app.services.report_period_content_service import normalize_sentiment_counts

        sent_norm = normalize_sentiment_counts(sentiment_counts)
        pos_n = int(sent_norm.get("正面") or 0)
        neu_n = int(sent_norm.get("中性") or 0)
        neg_n = int(sent_norm.get("负面") or 0)
        unk_n = int(sent_norm.get("未知") or 0)
        completed_n = int(kpis.get("completed_count") or 0) or (pos_n + neu_n + neg_n + unk_n)
        if completed_n > 0:
            neg_rate = round(neg_n * 100 / completed_n, 1)
            sentiment_line = (
                f"情绪分布（全样本 {completed_n}）："
                f"正面/中性/负面/未知 = {pos_n}/{neu_n}/{neg_n}/{unk_n}；"
                f"负面占比 {neg_rate}%（{neg_n}/{completed_n}），"
                f"正面占比 {round(pos_n * 100 / completed_n, 1)}%，"
                f"未知 {round(unk_n * 100 / completed_n, 1)}%。"
                f"写分析时负面/正面占比必须用上述全样本分母，禁止只用已标注子集重算。"
            )
        else:
            sentiment_line = "情绪分布：暂无完成样本"
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
            f"{sentiment_line}\n"
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

    def generate_cockpit_narrative(
        self,
        *,
        brand_name: str,
        facts: dict[str, Any],
    ) -> dict[str, Any]:
        """驾驶舱专用文案包（一次调用）：阶段文案 + P0/P1/P2 + 风险表 + 30/60/90 行动。

        2026-08-13 - 数字仍由监测映射；模型只写叙事，禁止改 KPI
        2026-08-13 - 接入品牌诊断分层提示词：监测事实→口径计算→分析判断→建议动作
        """
        if not self.report_enabled:
            raise DeepseekApiError("未开启 deepseek_report_enabled")

        brand = str(brand_name or "").strip() or "品牌"
        weak = facts.get("weak_prompts") or []
        strong = facts.get("strong_prompts") or []
        platforms = facts.get("platform_rows") or []
        competitors = facts.get("competitors") or []
        competitor_stats = facts.get("competitor_stats") if isinstance(facts.get("competitor_stats"), list) else []
        kpis = facts.get("kpis") or {}
        lanes = facts.get("kpi_lanes") if isinstance(facts.get("kpi_lanes"), dict) else {}
        acq = lanes.get("acquisition") if isinstance(lanes.get("acquisition"), dict) else {}
        defense = lanes.get("brand_defense") if isinstance(lanes.get("brand_defense"), dict) else {}
        sample_basis = facts.get("sample_basis") if isinstance(facts.get("sample_basis"), dict) else {}
        # 2026-08-13 - 格级 lane 曾缺 prompt_count → 模型写「防守问法数=0」与下方品牌问法冲突
        if "prompt_count" not in acq:
            acq = {
                **acq,
                "prompt_count": int(sample_basis.get("nonbrand_prompt_count") or 0),
            }
        if "prompt_count" not in defense:
            defense = {
                **defense,
                "prompt_count": int(sample_basis.get("brand_prompt_count") or 0),
            }
        all_kpi = lanes.get("all") if isinstance(lanes.get("all"), dict) else {}
        taxonomy = facts.get("prompt_taxonomy") if isinstance(facts.get("prompt_taxonomy"), list) else []
        intent_basis = facts.get("intent_basis") if isinstance(facts.get("intent_basis"), dict) else {}
        if not intent_basis:
            kb = facts.get("kpi_basis") if isinstance(facts.get("kpi_basis"), dict) else {}
            raw_intents = kb.get("intents") if isinstance(kb.get("intents"), dict) else {}
            intent_basis = {
                str(code): lanes for code, lanes in raw_intents.items() if isinstance(lanes, dict)
            }

        def _m(block: dict[str, Any], key: str, *, pct: bool = False) -> str:
            raw = block.get(key)
            if raw is None or raw == "":
                return "暂无数据"
            try:
                num = float(raw)
            except (TypeError, ValueError):
                return "暂无数据"
            return f"{num:.1f}%" if pct else f"{num:.1f}"

        weak_lines = [
            f"- {item.get('prompt')}: 格级提及率 {item.get('mention_rate')}%，均排 {item.get('avg_rank') or '暂无数据'}"
            f"{('；回答命中率 ' + str(item.get('answer_hit_rate')) + '%' ) if item.get('answer_hit_rate') is not None else ''}"
            for item in weak[:6]
            if isinstance(item, dict)
        ]
        strong_lines = [
            f"- {item.get('prompt')}: 格级提及率 {item.get('mention_rate')}%，均排 {item.get('avg_rank') or '暂无数据'}"
            f"{('；回答命中率 ' + str(item.get('answer_hit_rate')) + '%' ) if item.get('answer_hit_rate') is not None else ''}"
            for item in strong[:4]
            if isinstance(item, dict)
        ]
        plat_lines = [
            (
                f"- {item.get('name')}: 提及率 "
                f"{('暂无数据' if item.get('positive') is None else str(item.get('positive')) + '%')}，"
                f"均排 {item.get('rank') if item.get('rank') not in (None, '') else '暂无数据'}"
            )
            for item in platforms[:8]
            if isinstance(item, dict)
        ]
        tax_lines = []
        for item in taxonomy[:12]:
            if not isinstance(item, dict):
                continue
            hit = item.get("answer_hit_rate")
            hit_txt = (
                f"，回答命中率 {hit}%"
                if hit is not None and hit != ""
                else ""
            )
            tax_lines.append(
                f"- [{item.get('lane_label')}/{item.get('filter_label') or item.get('intent_label') or '未归类'}] "
                f"{item.get('prompt')}: 格级提及率 {item.get('mention_rate')}%，"
                f"均排 {item.get('avg_rank') if item.get('avg_rank') not in (None, '') else '暂无数据'}"
                f"{hit_txt}，样本 {item.get('sample_count') or 0}"
            )
        intent_lines: list[str] = []
        for code, intent_lanes in intent_basis.items():
            if not isinstance(intent_lanes, dict):
                continue
            label = str(intent_lanes.get("label") or code)
            nb = intent_lanes.get("nonbrand") if isinstance(intent_lanes.get("nonbrand"), dict) else {}
            bd = intent_lanes.get("brand") if isinstance(intent_lanes.get("brand"), dict) else {}
            intent_lines.append(
                f"- {label}({code}): 非品牌格 {int(nb.get('total_cells') or 0)}"
                f"（提及 {int(nb.get('mention_cells') or 0)}，率 {_m(nb, 'mention_rate', pct=True)}，"
                f"均排 {_m(nb, 'avg_rank')}）；"
                f"品牌格 {int(bd.get('total_cells') or 0)}"
                f"（提及 {int(bd.get('mention_cells') or 0)}，率 {_m(bd, 'mention_rate', pct=True)}，"
                f"均排 {_m(bd, 'avg_rank')}）"
            )
        scope_note = str(facts.get("platform_scope_note") or "").strip()
        monitored = facts.get("monitored_platforms") or []
        if isinstance(monitored, list) and monitored:
            monitored_txt = "、".join(str(x) for x in monitored if str(x).strip())
        else:
            monitored_txt = "（见平台槽位）"
        platform_count = int(facts.get("platform_count") or len(platforms) or 0)
        filter_mode = str(facts.get("filter_mode") or "intent")
        p1_level = "P1 · 问法补强" if platform_count <= 1 else "P1 · 平台覆盖"
        p0_level = "P0 · 意图攻坚" if filter_mode == "intent" else "P0 · 场景攻坚"

        json_schema = (
            "{\n"
            '  "stage_copy": {\n'
            '    "all": {"label":"管理层摘要","title":"含一个 <span>强调片段</span> 的标题 HTML","summary":"执行摘要：3-5个监测事实，须写明主 KPI 基于非品牌词获客"},\n'
            '    "recognition": {"label":"品牌认知","title":"...","summary":"可含品牌词防守口径；事实与推断分开"},\n'
            '    "selection": {"label":"竞品对标","title":"...","summary":"非品牌词共现/竞品同框"},\n'
            '    "procurement": {"label":"推荐名单","title":"...","summary":"推荐名单/入围类"},\n'
            '    "risk": {"label":"口碑评价","title":"...","summary":"口碑/风险；品牌词仅作防守分析"}\n'
            "  },\n"
            '  "priority_items": [\n'
            f'    {{"level_class":"p0","level":"{p0_level}","tone":"status-risk","tone_label":"缺口明显","title":"18字内","body":"须含：对应问法+数据证据+影响判断+优先级"}},\n'
            f'    {{"level_class":"p1","level":"{p1_level}","tone":"status-gap","tone_label":"需结构化","title":"18字内","body":"须含：对应问法+数据证据+影响判断+优先级"}},\n'
            '    {"level_class":"p2","level":"P2 · 优势放大","tone":"status-ok","tone_label":"基础较强","title":"18字内","body":"须含：对应问法+数据证据+影响判断+优先级"}\n'
            "  ],\n"
            '  "risk_rows": [\n'
            '    {"topic":"风险/问题（可含问法）","models":"监测覆盖范围","impact":"影响判断","evidence":"数据证据+建议证据","priority":"P0|P1","pill":"risk-high|risk-medium"}\n'
            "  ],\n"
            '  "actions": [\n'
            '    {"level_class":"p0","level":"P0 · 30 天","impact":"短标签","title":"标题","body":"绑定问法与预期指标","bullets":["内容载体","预期改善指标","复测方式"]},\n'
            '    {"level_class":"p1","level":"P1 · 60 天","impact":"短标签","title":"标题","body":"绑定问法与预期指标","bullets":["内容载体","预期改善指标","复测方式"]},\n'
            '    {"level_class":"p2","level":"P2 · 90 天","impact":"短标签","title":"标题","body":"绑定问法与预期指标","bullets":["内容载体","预期改善指标","复测方式"]}\n'
            "  ]\n"
            "}"
        )
        system_prompt = (
            "你是 GEO / AI 搜索可见度诊断分析师。"
            "请基于输入的监测数据生成品牌诊断报告（输出为驾驶舱 JSON，不是自由长文）。\n"
            "硬性要求：\n"
            "1. 不得编造数据。\n"
            "2. 所有数值必须来自输入数据，不允许自行估算。\n"
            "3. 必须区分：监测事实（直接来自数据）、分析判断（基于事实的合理推断）、优化建议（可执行动作）。"
            "无法从输入数据支持的结论必须标注为「推断」或不输出。\n"
            "4. 品牌词与非品牌词必须分开计算；禁止把品牌词数据混入主 KPI。\n"
            "5. 主 KPI 默认使用非品牌词获客口径："
            "获客提及率、获客平均推荐位、获客 Top3 率；品牌词问题不得进入这三项。\n"
            "6. 品牌词只用于品牌防守、口碑承接、竞品比较分析。\n"
            "7. 如果某项数据缺失，写「暂无数据」，不要补数字。\n"
            "8. 不要使用夸张营销话术。\n"
            "9. 不要把某个行业模板强套到所有品牌。\n"
            "10. 风险、优先级、行动建议必须引用具体问法和数据证据；禁止无数据来源的泛化建议。\n"
            "11. 每条问法须先分类：brand_query/non_brand_query；scene（电梯/机场/高铁/公交地铁/LED/none）；"
            # 2026-08-21 - 客户可见禁「选型标准/选型路径」品类；意图仅推荐名单/竞品对标/口碑评价/品牌认知（对齐换皮版-G 可见栏）
            "intent（推荐名单/竞品对标/口碑评价/品牌认知；禁止在 title/body/summary 写「选型标准」「选型路径」「选择标准」；"
            "阶段条 selection 必须写竞品对标，不得写技术选型或选型类问题）。"
            "scene!=none 时第二维为场景筛选，否则为问法意图。\n"
            "12. 若非品牌词获客问法数=0：三项主 KPI（获客提及率/均排/Top3）必须全部写「暂无数据」，"
            "禁止用品牌词或全量数据回填；执行摘要必须明确："
            "本次样本只能评估品牌防守，不能评估自然获客可见度。\n"
            "13. 主 KPI 数字必须直接引用输入中的 kpi_basis / kpi_lanes 格级结果，禁止自行重算或用 sample_basis 跨日率替代主 KPI。\n"
            "14. 若 intent_basis / kpi_basis.intents 某意图 total_cells>0，禁止写该意图「无样本/无数据」；"
            "须引用该意图格级 mention_rate / avg_rank。"
            "品牌词意图（口碑/品牌排名）用 brand 车道，勿套非品牌获客主 KPI；"
            "口碑若非品牌格=0但品牌格>0，必须写品牌防守口径，禁止把「非品牌口碑0格」写成主风险。\n"
            "15. 平台均排必须引用平台槽位已给出的均排；禁止在有均排数字时写「暂无数据」。\n"
            # 2026-08-21 - 强弱问法已是格级提及率；sample_basis 只能称回答命中率
            "16. weak_prompts/strong_prompts 中的「提及率」已是问法×平台格级，必须原样引用；"
            "sample_basis 数字只能称为「回答命中率」，禁止再叫「提及率」，"
            "禁止同一段里把格级提及率与回答命中率写成互相矛盾的同一口径。\n"
            # 2026-08-21 - 认知页禁把无防守绑成无法评估口碑；覆盖含 0% 意图
            "17. recognition（品牌认知）阶段：品牌词防守问法数为 0 时，只能写「无法评估品牌词防守/点名排名」，"
            "禁止写「无法评估品牌口碑」；口碑结论只放 risk（口碑评价）阶段。"
            "某意图格级提及率为 0% 仍算已覆盖，禁止因 0% 写该意图「未监测/无样本」。\n"
            "品牌诊断报告的主结论不得由模型自由发挥，必须由「监测事实 → 口径计算 → 分析判断 → 建议动作」逐层生成；"
            "任何无法从输入数据支持的结论都必须标注为「推断」或不输出。\n"
            "平台口径：未出现在监测平台列表中的平台=未监测，禁止写成提及率 0；"
            "禁止把系统约束句原文写进客户可见文案。\n"
            "若事实包 competitor_stats 中存在 hit_count>0，竞品对标阶段禁止写「未见/未提供竞品共现或同框」，必须引用具体竞品名与共现率；"
            "分析判断须写本品相对这些竞品的差距（同框强度/推荐位/证据）及可执行优化；"
            "禁止写「不是没有竞品」「并非没有竞品」这类纠错套话。\n"
            "title 可含单个 <span>…</span> 强调，其余字段纯文本。"
            "priority_items 必须恰好 3 条且 level_class 依次为 p0/p1/p2；"
            "actions 必须恰好 3 条对应 30/60/90 天；risk_rows 4~5 条。"
            "禁止验收口径、死日期单点承诺；量化用「争取提到约 A%～B%」表述。"
            "只输出 JSON。"
        )
        acq_count = int(acq.get("prompt_count") or 0)
        acq_zero_note = (
            "【硬约束】非品牌词获客问法数=0：主 KPI 三项必须为「暂无数据」，不得回填；"
            "结论只能谈品牌防守，不能谈自然获客可见度。\n"
            if acq_count <= 0
            else ""
        )
        # 2026-08-20 - 共现率进事实区，避免模型只看见名单就写「未见同框」
        comp_hit_rows = [
            r
            for r in competitor_stats[:8]
            if isinstance(r, dict) and str(r.get("name") or "").strip()
        ]
        if any(int(r.get("hit_count") or 0) > 0 for r in competitor_stats if isinstance(r, dict)):
            comp_block = (
                f"竞品名单：{('、'.join(str(x) for x in competitors[:8]) if competitors else '未配置')}\n"
                "竞品共现（非品牌词获客样本，须直接引用；hit_count>0 时禁止写未见/未提供同框）：\n"
                + "\n".join(
                    f"- {str(r.get('name') or '').strip()}: 共现率 {float(r.get('rate') or 0):.1f}%"
                    f"（命中 {int(r.get('hit_count') or 0)}/{int(r.get('sample_total') or 0)}）"
                    for r in comp_hit_rows
                )
                + "\n\n"
            )
        else:
            comp_block = (
                f"竞品名单：{('、'.join(str(x) for x in competitors[:8]) if competitors else '未配置')}\n"
                "竞品共现：暂无命中（才可写未见同框）。\n\n"
            )

        user_prompt = (
            f"品牌：{brand}\n"
            f"第二轴模式：{filter_mode}（scene=按场景归类；intent=按意图归类）\n"
            f"本窗监测平台（共 {platform_count} 个）：{monitored_txt}\n"
            f"平台口径（仅供遵守，勿原文写入客户文案）：{scope_note or '仅评价已列出的平台'}\n"
            f"{comp_block}"
            "【核心口径】\n"
            "A. 品牌词：含品牌名/别名/公司名、品牌+竞品对比、品牌怎么样/靠谱吗。\n"
            "B. 非品牌词：不含品牌名，但体现主动寻找方案/产品/机构/服务/推荐名单。\n"
            "主指标只基于非品牌词：获客提及率、获客平均推荐位、获客 Top3 率。\n"
            "品牌词单独：品牌防守提及率、品牌口碑情绪、品牌词平均排名、竞品对比表现。\n\n"
            f"{acq_zero_note}"
            "【已计算口径（直接引用，勿重算）】\n"
            f"- 非品牌词获客：问法数 {acq_count}，"
            f"获客提及率 {_m(acq, 'mention_rate', pct=True)}，"
            f"获客均排 {_m(acq, 'avg_rank')}，"
            f"获客 Top3 {_m(acq, 'top3_rate', pct=True)}\n"
            f"- 品牌词防守：问法数 {defense.get('prompt_count', 0)}，"
            f"防守提及率 {_m(defense, 'mention_rate', pct=True)}，"
            f"品牌词均排 {_m(defense, 'avg_rank')}，"
            f"Top3 {_m(defense, 'top3_rate', pct=True)}\n"
            f"- 全量辅助：问法数 {all_kpi.get('prompt_count', 0)}，"
            f"全量提及率 {_m(all_kpi, 'mention_rate', pct=True)}，"
            f"全量均排 {_m(all_kpi, 'avg_rank')}，"
            f"全量 Top3 {_m(all_kpi, 'top3_rate', pct=True)}，"
            f"负面关联 {_m(all_kpi, 'negative_rate', pct=True)}，"
            f"信源引用 {_m(all_kpi, 'citation_rate', pct=True)}\n"
            f"- 壳映射主 KPI（=非品牌词获客；样本为 0 时三项均为暂无数据）："
            f"提及率 {_m(kpis, 'visibility', pct=True)}，"
            f"均排 {_m(kpis, 'rank')}，"
            f"Top3 {_m(kpis, 'decision', pct=True)}，"
            f"负面 {_m(kpis, 'negative', pct=True)}，"
            f"引用 {_m(kpis, 'citation', pct=True)}\n\n"
            "【问法归类与样本】\n"
            f"{chr(10).join(tax_lines) or '- 暂无数据'}\n\n"
            "【意图格级样本（有格则禁止写无样本）】\n"
            f"{chr(10).join(intent_lines) or '- 暂无意图切片'}\n\n"
            "【非品牌词弱问法】\n"
            f"{chr(10).join(weak_lines) or '- 暂无数据'}\n\n"
            "【非品牌词强问法】\n"
            f"{chr(10).join(strong_lines) or '- 暂无数据'}\n\n"
            "【平台槽位（仅这些有样本）】\n"
            f"{chr(10).join(plat_lines) or '- 暂无数据'}\n\n"
            "请按「执行摘要 / 核心指标口径 / 问法归类结论 / 关键问题诊断 / 优化建议」组织内容，"
            "并映射到下列 JSON 字段（all.summary=执行摘要；priority/risk=关键问题；actions=优化建议）。\n"
            f"请输出 JSON：\n{json_schema}"
        )
        content = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.35,
            max_tokens=3200,
            source="cockpit-narrative",
        )
        payload = self._parse_json_payload(content)
        if not isinstance(payload, dict):
            raise DeepseekApiError("DeepSeek 驾驶舱 JSON 格式错误")
        return _normalize_cockpit_narrative(payload, brand=brand)

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
        prompt_variant: str = "current",
    ) -> dict[str, Any]:
        """Extract brand list rank from a monitor answer using ranking rules."""
        aliases = "、".join(term.strip() for term in brand_terms if str(term or "").strip())
        truncate_note = "（正文已截断）" if truncated else ""
        # 2026-08-21 - 方案 C：强制先列主表品牌序再报位次；忽略思考/搜索引用区品牌名
        # 2026-08-21 - 补强：只用主推荐表/主列表，禁止次要段（纠人工改过的错因 1/4/5）
        # 2026-08-24 - 近3天错样：分档跨段累加（进口3+国产4=7）、思考区品牌污染
        # 2026-08-24 - 口径收口：有分类算分类 → 有表算表 → 否则全文出场（含顺口提）；禁止有露出却 rank=null
        # 2026-08-24 - prompt 瘦身：合并跨档/跨段/城市子组为「计位范围锁定」；user 去掉重复案例与自检
        builder = (
            _build_brand_rank_prompts_legacy
            if str(prompt_variant or "current").strip().lower() == "legacy"
            else _build_brand_rank_prompts
        )
        system_prompt, user_prompt = builder(
            monitor_keyword=monitor_keyword,
            prompt=prompt,
            aliases=aliases,
            answer_text=answer_text,
            truncate_note=truncate_note,
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
