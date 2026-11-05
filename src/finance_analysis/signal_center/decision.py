"""V2 research decisions with exact snapshot evidence references and explicit abstention."""

from datetime import date
from typing import Any, Literal
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from finance_analysis.signal_center.prompt import parse_object

from finance_analysis.signal_center.prompt_template import GUIDANCE

PROMPT_VERSION = "signal-center-v2-evidence"
SYSTEM_PROMPT = GUIDANCE.format(objective="本轮为最终决策：从已入围候选中选择0–3个，给出BUY或NO_TRADE及可核验的依据。") + """# 交付

## 证据要求
每个BUY至少引用两条不同字段的非空输入事实；原样复制value，不得引用未提供的上游明细。
顶层evidence最多12项；每只推荐的evidence必须为2–12项，同一field不得重复。
每只推荐的positive_signals、risks、invalidations各1–12项，external_sources最多8项。
同一条证据可用supports同时支持多个主张；通过合并表述、复用证据控制数量，不为每个主张重复建立证据。
说明其支持何种推断（interpretation）。事实可机检，解释仍是模型判断，引用相同底层事实不代表独立共振。
BUY必须有明确优势、主要反对证据、风险和可观察失效条件；不明确则不推荐，绝不补足三个名额。

## 输出格式

只输出一个JSON对象，不使用代码围栏或额外正文，不添加契约外字段。
最终JSON严格为：market, signal_date, decision(BUY|NO_TRADE), thesis, no_trade_reason, evidence, recommendations。
顶层evidence用于解释整体结论；有最终候选时NO_TRADE必须引用至少一条事实，supports为["thesis"]。BUY可留空。
recommendations数组每项严格为：symbol, confidence(low|medium|high), thesis, positive_signals(字符串数组),
risks(非空字符串数组), invalidations(非空字符串数组), evidence(数组), external_sources(数组)。
evidence项严格为{field,value,data_as_of,interpretation,supports}；external_sources项严格为{url,title,published_date,excerpt}。
每条正向依据、风险、失效条件必须有事实引用：supports列出对应数组下标，如["positive_signals.0","invalidations.0"]。
BUY时recommendations有1至3项且no_trade_reason=null；NO_TRADE时数组为空，no_trade_reason为
NO_CLEAR_EDGE/OVERHEATED/SIGNAL_CONFLICT/INSUFFICIENT_EVIDENCE。理由全部中文。只输出单个JSON对象。"""
SCREEN_SYSTEM_PROMPT = GUIDANCE.format(objective="本轮为候选初筛：从本批候选中选择0–3个进入最终比较，允许空选；入围不等于最终BUY推荐。") + """# 交付

只输出一个JSON对象，不使用代码围栏或额外正文，不添加其他字段：

```json
{"symbols": [], "reason": "中文理由"}
```

- symbols：0–3个candidates中的代码，不可重复；没有合适候选时为空数组。
- reason：简要解释入围优势、主要风险及淘汰原因；空选时说明原因。
- 区分快照判断与实际执行的联网核查；未核查的关键风险须明确说明。
"""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Evidence(StrictModel):
    field: str = Field(min_length=1, max_length=500)
    value: Any
    data_as_of: str
    interpretation: str = Field(min_length=1, max_length=2000)
    supports: list[str] = Field(min_length=1, max_length=36)


class ExternalSource(StrictModel):
    url: str = Field(max_length=2000)
    title: str = Field(min_length=1, max_length=500)
    published_date: str | None
    excerpt: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def valid_url(self):
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid source URL")
        if self.published_date is not None:
            date.fromisoformat(self.published_date)
        if not self.title.strip() or not self.excerpt.strip():
            raise ValueError("Empty external source")
        return self


class Recommendation(StrictModel):
    symbol: str
    confidence: Literal["low", "medium", "high"]
    thesis: str = Field(min_length=1, max_length=6000)
    positive_signals: list[str] = Field(min_length=1, max_length=12)
    risks: list[str] = Field(min_length=1, max_length=12)
    invalidations: list[str] = Field(min_length=1, max_length=12)
    evidence: list[Evidence] = Field(min_length=2, max_length=12)
    external_sources: list[ExternalSource] = Field(max_length=8)


class Decision(StrictModel):
    market: Literal["CN", "US"]
    signal_date: str
    decision: Literal["BUY", "NO_TRADE"]
    thesis: str = Field(min_length=1, max_length=6000)
    no_trade_reason: Literal["NO_CLEAR_EDGE", "OVERHEATED", "SIGNAL_CONFLICT", "INSUFFICIENT_EVIDENCE"] | None
    evidence: list[Evidence] = Field(max_length=12)
    recommendations: list[Recommendation] = Field(max_length=3)

    @model_validator(mode="after")
    def valid_choice(self):
        date.fromisoformat(self.signal_date)
        if self.decision == "BUY":
            if not self.recommendations or self.no_trade_reason is not None:
                raise ValueError("BUY requires recommendations")
        elif self.recommendations or self.no_trade_reason is None:
            raise ValueError("NO_TRADE requires an empty selection and a reason")
        symbols = [r.symbol for r in self.recommendations]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Duplicate recommendation")
        texts = [self.thesis]
        for r in self.recommendations:
            texts.extend(
                [r.thesis, *r.positive_signals, *r.risks, *r.invalidations, *(e.interpretation for e in r.evidence)]
            )
        if any(not v.strip() or len(v) > 6000 for v in texts):
            raise ValueError("Empty or oversized rationale")
        return self


def parse_decision(text, snapshot, search_evidence=None):
    result = Decision.model_validate(parse_object(text))
    if (result.market, result.signal_date) != (snapshot["market"], snapshot["signal_date"]):
        raise ValueError("Decision market/date mismatch")
    candidates = {c["symbol"] for c in snapshot["candidates"]}
    catalog = snapshot["evidence_catalog"]

    def check_evidence(evidence, allowed_symbols):
        fact = catalog.get(evidence.field)
        if not fact or fact["symbol"] not in allowed_symbols:
            raise ValueError("Unknown or cross-symbol evidence")
        # JSON has a single number type: 80 and 80.0 are equal, but True cannot stand in for 1.
        expected, actual = fact["value"], evidence.value
        numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (expected, actual))
        if expected != actual or (not numbers and type(expected) is not type(actual)):
            raise ValueError("Evidence value mismatch")
        if fact["data_as_of"] != evidence.data_as_of:
            raise ValueError("Evidence date mismatch")
        if not evidence.interpretation.strip() or len(set(evidence.supports)) != len(evidence.supports):
            raise ValueError("Invalid evidence interpretation/supports")
        return fact

    if result.decision == "NO_TRADE" and candidates and not result.evidence:
        raise ValueError("NO_TRADE requires decision evidence")
    if len({e.field for e in result.evidence}) != len(result.evidence):
        raise ValueError("Duplicate decision evidence")
    for e in result.evidence:
        check_evidence(e, candidates | {None})
        if e.supports != ["thesis"]:
            raise ValueError("Decision evidence must support thesis")
    for pick in result.recommendations:
        if pick.symbol not in candidates:
            raise ValueError("Selected symbol is not a finalist")
        if len({e.field for e in pick.evidence}) != len(pick.evidence):
            raise ValueError("Duplicate evidence")
        required = {
            f"{key}.{index}"
            for key in ("positive_signals", "risks", "invalidations")
            for index in range(len(getattr(pick, key)))
        }
        covered, specific = set(), False
        for evidence in pick.evidence:
            fact = check_evidence(evidence, {None, pick.symbol})
            if not set(evidence.supports) <= required:
                raise ValueError("Evidence supports unknown claim")
            covered.update(evidence.supports)
            specific |= fact["symbol"] == pick.symbol
        if not specific or covered != required:
            raise ValueError("Every BUY claim needs evidence and security-specific facts")
        for source in pick.external_sources:
            if source.published_date and source.published_date > result.signal_date:
                raise ValueError("External evidence is after signal date")
        if search_evidence is not None and pick.external_sources and search_evidence.get("status") != "confirmed":
            raise ValueError("External sources require transport-confirmed search")
    return result.model_dump()


def parse_screen(text, symbols):
    value = parse_object(text)
    if not isinstance(value, dict) or set(value) != {"symbols", "reason"}:
        raise ValueError("Invalid screening output")
    chosen = value["symbols"]
    if (
        not isinstance(chosen, list)
        or len(chosen) > 3
        or any(not isinstance(s, str) for s in chosen)
        or len(set(chosen)) != len(chosen)
        or not set(chosen) <= set(symbols)
    ):
        raise ValueError("Invalid screening symbols")
    if not isinstance(value["reason"], str) or not value["reason"].strip() or len(value["reason"]) > 6000:
        raise ValueError("Invalid screening reason")
    return value
