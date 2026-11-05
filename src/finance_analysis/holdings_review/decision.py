"""Bounded structured decisions, with portfolio membership enforced by code."""

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from finance_analysis.llm import LLMClient, LLMRequest
from finance_analysis.llm.json_parse import parse_llm_json_response
from finance_analysis.holdings_review.prompt import SYSTEM, render_input
from finance_analysis.llm.prompting import PromptBudgetExceeded


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PositionAdvice(StrictModel):
    position_id: str = Field(max_length=64)
    symbol: str = Field(max_length=32)
    action: Literal["HOLD", "BUY", "REDUCE", "SELL", "WATCH"]
    change_pct: float = Field(default=0, ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=500)
    condition: str = Field(default="", max_length=300)
    invalidation: str = Field(default="", max_length=300)
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"


class SectorView(StrictModel):
    name: str = Field(max_length=80)
    strength: Literal["STRONG", "NEUTRAL", "WEAK"]
    rationale: str = Field(max_length=350)


class Risk(StrictModel):
    title: str = Field(max_length=100)
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    detail: str = Field(max_length=500)


class ReviewDecision(StrictModel):
    market_state: Literal["RISK_ON", "NEUTRAL", "RISK_OFF", "UNCERTAIN"]
    conclusion: str = Field(min_length=1, max_length=900)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    sectors: list[SectorView] = Field(default_factory=list, max_length=6)
    risks: list[Risk] = Field(default_factory=list, max_length=6)
    positions: list[PositionAdvice] = Field(default_factory=list)
    watchpoints: list[str] = Field(default_factory=list, max_length=6)


def validate_decision(raw, context):
    decision = ReviewDecision.model_validate(raw).model_dump()
    expected = {p["position_id"]: p for p in context["holdings"]}
    output = {}
    for row in decision["positions"]:
        holding = expected.get(row["position_id"])
        if not holding or row["symbol"] != holding["symbol"] or row["position_id"] in output:
            raise ValueError("Advice must uniquely reference a frozen portfolio position")
        action = row["action"]
        if action in {"BUY", "REDUCE"} and row["change_pct"] <= 0:
            raise ValueError("Active advice must include a positive percentage")
        if action == "BUY" and not row["condition"].strip():
            raise ValueError("BUY requires an explicit add-to-position condition")
        if action == "REDUCE" and row["change_pct"] >= 100:
            row["action"] = "SELL"
        if not holding.get("data_complete") and row["action"] in {"BUY", "REDUCE", "SELL"}:
            row.update(action="WATCH", change_pct=0, confidence="LOW")
            row["rationale"] = "行情证据不完整，主动建议已降为观察。" + row["rationale"][:450]
        if row["action"] == "SELL":
            row["change_pct"] = 100
        elif row["action"] in {"HOLD", "WATCH"}:
            row["change_pct"] = 0
        if (
            context.get("market") == "CN"
            and holding.get("quantity") is not None
            and row["action"] in {"REDUCE", "SELL"}
        ):
            quantity = holding.get("quantity") or 0
            bought = holding.get("today_buy_quantity") or 0
            allowed = max(0, (quantity - bought) / quantity * 100) if quantity > 0 else 0
            if allowed <= 0:
                row.update(action="WATCH", change_pct=0, confidence="LOW")
                row["rationale"] = "当前持仓均为当日买入，T+1约束下不建议当日卖出。" + row["rationale"][:420]
            elif bought > 0 and row["change_pct"] > allowed:
                row.update(action="REDUCE", change_pct=round(allowed, 4))
                row["rationale"] = "已按T+1限制缩小减仓比例。" + row["rationale"][:450]
        output[row["position_id"]] = row
    for key, holding in expected.items():
        if key not in output:
            output[key] = PositionAdvice(
                position_id=key,
                symbol=holding["symbol"],
                action="WATCH",
                confidence="LOW",
                rationale="模型未对该持仓形成完整建议，维持观察，不推断买卖动作。",
            ).model_dump()
    added_value = sum(
        (expected[key].get("market_value") or 0) * row["change_pct"] / 100
        for key, row in output.items()
        if row["action"] == "BUY"
    )
    cash = context.get("portfolio", {}).get("cash")
    if added_value and (cash is None or added_value > cash + 0.01):
        raise ValueError("Aggregate BUY advice exceeds the registered cash balance")
    if not context.get("portfolio", {}).get("valuation_complete", False):
        for row in output.values():
            if row["action"] == "BUY":
                row.update(action="WATCH", change_pct=0, confidence="LOW")
                row["rationale"] = "组合估值不完整，加仓建议降为观察。" + row["rationale"][:450]
    decision["positions"] = [output[key] for key in expected]
    decision["watchpoints"] = [text[:400] for text in decision["watchpoints"]]
    if "indices" in context and not any(
        index.get("daily_count", 0) >= 10 and index.get("current_price") for index in context["indices"]
    ):
        decision["confidence"], decision["market_state"] = "LOW", "UNCERTAIN"
    decision["degraded"] = False
    return decision


def fallback(context, reason):
    return {
        "market_state": "UNCERTAIN",
        "conclusion": "本轮未取得有效模型结论，保留数据快照供人工复核。",
        "confidence": "LOW",
        "sectors": [],
        "risks": [{"title": "复盘降级", "severity": "MEDIUM", "detail": reason}],
        "positions": [
            PositionAdvice(
                position_id=p["position_id"],
                symbol=p["symbol"],
                action="WATCH",
                rationale="未取得可靠的结构化模型建议，请结合持仓证据人工复核。",
            ).model_dump()
            for p in context["holdings"]
        ],
        "watchpoints": [],
        "degraded": True,
    }


class ReviewDecisionMaker:
    def __init__(self, client=None):
        self.client = client

    def decide(self, uid, context):
        evidence = {"requested": True, "status": "unavailable", "citations": []}
        try:
            client = self.client or LLMClient()
            if not client.is_available():
                return fallback(context, "LLM未配置或当前不可用"), evidence, {}
            payload = render_input(context)

            def validate(text):
                validate_decision(parse_llm_json_response(text), context)

            result = client.complete_text(
                LLMRequest(
                    system_prompt=SYSTEM,
                    prompt=payload,
                    call_type="holdings_review",
                    uid=uid,
                    web_search=True,
                ),
                validator=validate,
            )
            decision = validate_decision(parse_llm_json_response(result.text), context)
            evidence = result.search_evidence or evidence
            return decision, evidence, {"model": result.model, "backend": result.backend}
        except PromptBudgetExceeded:
            return fallback(context, "持仓输入含系统指令超过40,000字符，未截断或遗漏持仓来生成建议"), evidence, {}
        except Exception as exc:
            # No provider payload, prompt or credentials in user-facing errors.
            return fallback(context, f"结构化模型复盘不可用（{type(exc).__name__}）"), evidence, {}


def sources(evidence):
    result, seen = [], set()
    if evidence.get("status") != "confirmed":
        return result
    for row in evidence.get("citations", []):
        url = str(row.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme in {"https", "http"} and parsed.netloc and url not in seen:
            result.append({"title": str(row.get("title") or parsed.netloc)[:150], "url": url[:2048]})
            seen.add(url)
    return result[:8]
