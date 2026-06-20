# -*- coding: utf-8 -*-
"""Chip / price-position fills and structural decision-stability calibration."""

import logging
import math
import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from finance_analysis.reporting.localization import (
    infer_decision_type_from_advice,
    localize_chip_health,
    normalize_report_language,
)
from finance_analysis.analysis.report_text_utils import (
    _is_meaningful_text,
    _is_value_placeholder,
    _safe_float,
)

if TYPE_CHECKING:
    from finance_analysis.analysis.stock_report_analyzer import AnalysisResult

logger = logging.getLogger(__name__)

_CHIP_KEYS: tuple = ("profit_ratio", "avg_cost", "concentration", "chip_health")

_STRUCTURAL_RISK_PHRASE_HINTS = (
    "重大利空",
    "重大风险",
    "关键风险",
    "减持",
    "高位减持",
    "退市",
    "退市风险",
    "停牌",
    "重大问询",
    "处罚",
    "限售",
    "违规",
    "违规风险",
    "诉讼",
    "问询",
    "监管",
    "财务",
    "审计",
    "爆雷",
    "暴雷",
    "违约",
    "违约风险",
    "流动性危机",
    "债务",
    "清算",
    "破产",
    "重大变脸",
    "major risk",
    "material adverse",
    "suspension",
    "delisting",
    "regulatory",
    "downgrade",
    "liquidity",
    "default",
)

_CAPITAL_FLOW_UNAVAILABLE_STATUS = {
    "not_supported",
    "not supported",
    "unsupported",
    "unavailable",
    "not_available",
    "not available",
    "none",
    "na",
    "n/a",
    "null",
    "missing",
}

def _derive_chip_health(profit_ratio: float, concentration_90: float, language: str = "zh") -> str:
    """Derive chip_health from profit_ratio and concentration_90."""
    if profit_ratio >= 0.9:
        return localize_chip_health("警惕", language)  # 获利盘极高
    if concentration_90 >= 0.25:
        return localize_chip_health("警惕", language)  # 筹码分散
    if concentration_90 < 0.15 and 0.3 <= profit_ratio < 0.9:
        return localize_chip_health("健康", language)  # 集中且获利比例适中
    return localize_chip_health("一般", language)
def _build_chip_structure_from_data(chip_data: Any, language: str = "zh") -> Dict[str, Any]:
    """Build chip_structure dict from ChipDistribution or dict."""
    if hasattr(chip_data, "profit_ratio"):
        pr = _safe_float(chip_data.profit_ratio)
        ac = chip_data.avg_cost
        c90 = _safe_float(chip_data.concentration_90)
    else:
        d = chip_data if isinstance(chip_data, dict) else {}
        pr = _safe_float(d.get("profit_ratio"))
        ac = d.get("avg_cost")
        c90 = _safe_float(d.get("concentration_90"))
    chip_health = _derive_chip_health(pr, c90, language=language)
    return {
        "profit_ratio": f"{pr:.1%}",
        "avg_cost": ac if (ac is not None and _safe_float(ac) != 0.0) else "N/A",
        "concentration": f"{c90:.2%}",
        "chip_health": chip_health,
    }
def fill_chip_structure_if_needed(result: "AnalysisResult", chip_data: Any) -> None:
    """When chip_data exists, fill chip_structure placeholder fields from chip_data (in-place)."""
    if not result or not chip_data:
        return
    try:
        if not result.dashboard:
            result.dashboard = {}
        dash = result.dashboard
        # Use `or {}` rather than setdefault so that an explicit `null` from LLM is also replaced
        dp = dash.get("data_perspective") or {}
        dash["data_perspective"] = dp
        cs = dp.get("chip_structure") or {}
        filled = _build_chip_structure_from_data(
            chip_data,
            language=getattr(result, "report_language", "zh"),
        )
        # Start from a copy of cs to preserve any extra keys the LLM may have added
        merged = dict(cs)
        for k in _CHIP_KEYS:
            if _is_value_placeholder(merged.get(k)):
                merged[k] = filled[k]
        if merged != cs:
            dp["chip_structure"] = merged
            logger.info("[chip_structure] Filled placeholder chip fields from data source (Issue #589)")
    except Exception as e:
        logger.warning("[chip_structure] Fill failed, skipping: %s", e)


_PRICE_POS_KEYS = ("ma5", "ma10", "ma20", "bias_ma5", "bias_status", "current_price", "support_level", "resistance_level")


def fill_price_position_if_needed(
    result: "AnalysisResult",
    trend_result: Any = None,
    realtime_quote: Any = None,
) -> None:
    """Fill missing price_position fields from trend_result / realtime data (in-place)."""
    if not result:
        return
    try:
        if not result.dashboard:
            result.dashboard = {}
        dash = result.dashboard
        dp = dash.get("data_perspective") or {}
        dash["data_perspective"] = dp
        pp = dp.get("price_position") or {}

        computed: Dict[str, Any] = {}
        if trend_result:
            tr = trend_result if isinstance(trend_result, dict) else (
                trend_result.__dict__ if hasattr(trend_result, "__dict__") else {}
            )
            computed["ma5"] = tr.get("ma5")
            computed["ma10"] = tr.get("ma10")
            computed["ma20"] = tr.get("ma20")
            computed["bias_ma5"] = tr.get("bias_ma5")
            computed["current_price"] = tr.get("current_price")
            support_levels = tr.get("support_levels") or []
            resistance_levels = tr.get("resistance_levels") or []
            if support_levels:
                computed["support_level"] = support_levels[0]
            if resistance_levels:
                computed["resistance_level"] = resistance_levels[0]
        if realtime_quote:
            rq = realtime_quote if isinstance(realtime_quote, dict) else (
                realtime_quote.to_dict() if hasattr(realtime_quote, "to_dict") else {}
            )
            if _is_value_placeholder(computed.get("current_price")):
                computed["current_price"] = rq.get("price")

        filled = False
        for k in _PRICE_POS_KEYS:
            if _is_value_placeholder(pp.get(k)) and not _is_value_placeholder(computed.get(k)):
                pp[k] = computed[k]
                filled = True
        if filled:
            dp["price_position"] = pp
            logger.info("[price_position] Filled placeholder fields from computed data")
    except Exception as e:
        logger.warning("[price_position] Fill failed, skipping: %s", e)
def stabilize_decision_with_structure(
    result: "AnalysisResult",
    trend_result: Any = None,
    fundamental_context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Calibrate aggressive buy/sell advice with price levels and capital flow.

    The LLM can overreact to one-day price movement.  This guard keeps the
    public `decision_type` enum stable while allowing richer neutral wording
    such as 震荡/洗盘观察 when support, resistance, and fund flow do not confirm
    an immediate buy/sell action.
    """
    if not result:
        return

    try:
        language = normalize_report_language(getattr(result, "report_language", "zh"))
        dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}
        data_perspective = dashboard.get("data_perspective") if isinstance(dashboard, dict) else {}
        if not isinstance(data_perspective, dict):
            data_perspective = {}
        price_position = data_perspective.get("price_position")
        if not isinstance(price_position, dict):
            price_position = {}

        trend_dict = _as_dict_for_decision_guard(trend_result)
        current_price = _first_numeric_value(
            getattr(result, "current_price", None),
            price_position.get("current_price"),
            trend_dict.get("current_price"),
        )
        support = _first_numeric_value(
            price_position.get("support_level"),
            _first_list_value(trend_dict.get("support_levels")),
        )
        resistance = _first_numeric_value(
            price_position.get("resistance_level"),
            _first_list_value(trend_dict.get("resistance_levels")),
        )
        flow_bias, flow_reason = _capital_flow_bias_with_status(fundamental_context)
        if flow_bias == "unavailable":
            if isinstance(fundamental_context, dict) and "capital_flow" in fundamental_context:
                _set_decision_stability_unavailable(
                    result,
                    language,
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_status=flow_reason,
                )
            return
        decision_type = infer_decision_type_from_advice(
            getattr(result, "decision_type", ""),
            default=getattr(result, "decision_type", "hold") or "hold",
        )
        decision_type = decision_type if decision_type in {"buy", "hold", "sell"} else "hold"

        if current_price is None:
            return

        broke_support = support is not None and current_price < support * 0.985
        near_support = support is not None and not broke_support and current_price <= support * 1.03
        breakout = resistance is not None and current_price > resistance * 1.01
        near_resistance = (
            resistance is not None
            and not breakout
            and current_price >= resistance * 0.97
        )
        mid_range = (
            support is not None
            and resistance is not None
            and support * 1.03 < current_price < resistance * 0.97
        )

        has_significant_risk = _has_structural_risk_alert(result)

        if decision_type == "buy":
            if near_resistance and flow_bias != "inflow":
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="range",
                    reason_key="buy_near_resistance",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
            elif flow_bias == "outflow" and not breakout:
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="range",
                    reason_key="buy_with_outflow",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
            elif mid_range and flow_bias == "neutral":
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="range",
                    reason_key="hold_mid_range",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
        elif decision_type == "sell":
            if near_support and (flow_bias != "outflow") and not has_significant_risk:
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="shakeout",
                    reason_key="sell_near_support",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
            elif flow_bias == "inflow" and not broke_support and not has_significant_risk:
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="hold",
                    reason_key="sell_with_inflow",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
        elif decision_type == "hold":
            change_pct = _first_numeric_value(getattr(result, "change_pct", None))
            if change_pct is not None and change_pct < 0 and near_support and flow_bias != "outflow":
                _set_structural_hold_wording(
                    result,
                    language,
                    advice_key="shakeout",
                    reason_key="hold_shakeout",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
            elif mid_range and flow_bias == "neutral":
                _set_structural_hold_wording(
                    result,
                    language,
                    advice_key="range",
                    reason_key="hold_mid_range",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
        _sync_stability_dashboard_fields(result)
    except Exception as exc:
        logger.warning("[decision_stability] skipped: %s", exc)
def _has_structural_risk_alert(result: "AnalysisResult") -> bool:
    dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}

    risk_text = getattr(result, "risk_warning", "")
    if _is_significant_structural_risk(risk_text):
        return True

    intelligence = dashboard.get("intelligence") if isinstance(dashboard, dict) else None
    if isinstance(intelligence, dict):
        risk_alerts = intelligence.get("risk_alerts")
        if isinstance(risk_alerts, str):
            if _is_significant_structural_risk(risk_alerts):
                return True
        elif isinstance(risk_alerts, (list, tuple, set)):
            if any(_is_significant_structural_risk(item) for item in risk_alerts):
                return True

    core_conclusion = dashboard.get("core_conclusion") if isinstance(dashboard, dict) else None
    if isinstance(core_conclusion, dict):
        signal_type = str(core_conclusion.get("signal_type", "")).strip()
        if _is_significant_structural_risk(signal_type):
            return True
    return False
def _is_significant_structural_risk(value: Any) -> bool:
    text = str(value or "").strip()
    if not _is_meaningful_text(text):
        return False

    normalized = text.lower()
    if any(keyword in normalized for keyword in _STRUCTURAL_RISK_PHRASE_HINTS):
        return True

    return "重大" in text and "风险" in normalized
def _sync_stability_dashboard_fields(result: "AnalysisResult") -> None:
    dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}
    result.dashboard = dashboard
    dashboard["sentiment_score"] = getattr(result, "sentiment_score", None)
    dashboard["operation_advice"] = getattr(result, "operation_advice", None)
    dashboard["decision_type"] = getattr(result, "decision_type", None)
def _as_dict_for_decision_guard(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        try:
            converted = value.to_dict()
            return converted if isinstance(converted, dict) else {}
        except Exception:
            return {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}
def _first_list_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value
def _coerce_numeric_value(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if math.isfinite(float(value)):
            return float(value)
        return None
    text = str(value).replace(",", "").replace("，", "").strip()
    if not text or text.upper() in {"N/A", "NA", "NONE", "NULL"}:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None
def _first_numeric_value(*values: Any) -> Optional[float]:
    for value in values:
        if isinstance(value, (list, tuple)):
            nested = _first_numeric_value(*value)
            if nested is not None:
                return nested
            continue
        numeric = _coerce_numeric_value(value)
        if numeric is not None:
            return numeric
    return None
def _capital_flow_bias(fundamental_context: Optional[Dict[str, Any]]) -> str:
    return _capital_flow_bias_with_status(fundamental_context)[0]

def _capital_flow_bias_with_status(
    fundamental_context: Optional[Dict[str, Any]],
) -> tuple[str, str]:
    if not isinstance(fundamental_context, dict):
        return "unavailable", "invalid_context"
    block = fundamental_context.get("capital_flow")
    if not isinstance(block, dict):
        return "unavailable", "capital_flow_block_missing"
    status = str(block.get("status") or "").strip().lower()
    normalized_status = status.replace("-", " ").replace("_", " ").strip()
    if normalized_status in _CAPITAL_FLOW_UNAVAILABLE_STATUS or "not supported" in normalized_status:
        return "unavailable", status or "not_supported"
    data = block.get("data") if isinstance(block.get("data"), dict) else block
    stock_flow = data.get("stock_flow") if isinstance(data, dict) else None
    if not isinstance(stock_flow, dict) or not stock_flow:
        return "unavailable", "empty_stock_flow"

    def _flow_direction(value: Optional[float]) -> Optional[str]:
        if value is None or value == 0:
            return None
        return "inflow" if value > 0 else "outflow"

    numeric_values = [
        _coerce_numeric_value(stock_flow.get("main_net_inflow")),
        _coerce_numeric_value(stock_flow.get("inflow_5d")),
        _coerce_numeric_value(stock_flow.get("inflow_10d")),
    ]
    if all(value is None for value in numeric_values):
        return "unavailable", "missing_or_na_flow_fields"

    ordered_signals = [
        _flow_direction(value) for value in numeric_values
    ]
    directions = {signal for signal in ordered_signals if signal is not None}
    if not directions or len(directions) > 1:
        return "neutral", "conflict_or_missing"
    for signal in ordered_signals:
        if signal is not None:
            return signal, "ok"
    return "neutral", "neutral"
def _capital_flow_status_for_stability(reason: str, language: str) -> str:
    normalized = str(reason or "").strip().lower()
    if "not_supported" in normalized or "unsupported" in normalized or "not available" in normalized:
        return "市场资金流服务暂不支持" if language == "zh" else "Capital flow source unsupported"
    if "empty_stock_flow" in normalized or "missing" in normalized:
        return "资金流数据缺失" if language == "zh" else "capital flow data unavailable"
    return "资金流数据不可用" if language == "zh" else "capital flow unavailable"
def _set_decision_stability_unavailable(
    result: "AnalysisResult",
    language: str,
    *,
    current_price: Optional[float],
    support: Optional[float],
    resistance: Optional[float],
    flow_status: str,
) -> None:
    dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}
    result.dashboard = dashboard
    dashboard["decision_stability"] = {
        "applied": False,
        "reason": "资金流不可用，未使用资金流校准" if language == "zh" else "Capital flow unavailable; stability calibration not applied",
        "capital_flow_status": _capital_flow_status_for_stability(flow_status, language),
        "current_price": current_price,
        "support": support,
        "resistance": resistance,
        "capital_flow_bias": "unavailable",
    }
    _sync_stability_dashboard_fields(result)
def _downgrade_to_structural_hold(
    result: "AnalysisResult",
    language: str,
    *,
    advice_key: str,
    reason_key: str,
    current_price: float,
    support: Optional[float],
    resistance: Optional[float],
    flow_bias: str,
) -> None:
    result.decision_type = "hold"
    try:
        score = int(getattr(result, "sentiment_score", 50))
    except (TypeError, ValueError):
        score = 50
    result.sentiment_score = min(59, max(45, score))
    _set_structural_hold_wording(
        result,
        language,
        advice_key=advice_key,
        reason_key=reason_key,
        current_price=current_price,
        support=support,
        resistance=resistance,
        flow_bias=flow_bias,
    )
def _set_structural_hold_wording(
    result: "AnalysisResult",
    language: str,
    *,
    advice_key: str,
    reason_key: str,
    current_price: float,
    support: Optional[float],
    resistance: Optional[float],
    flow_bias: str,
) -> None:
    advice = {
        "zh": {
            "range": "震荡观望",
            "shakeout": "洗盘观察",
            "hold": "持有观察",
        },
        "en": {
            "range": "Range-bound watch",
            "shakeout": "Shakeout watch",
            "hold": "Hold and watch",
        },
    }[language].get(advice_key, "持有观察" if language == "zh" else "Hold and watch")
    reason_templates = {
        "zh": {
            "buy_near_resistance": "价格接近压力位且主力资金未确认流入，不宜仅因短线反弹追买。",
            "buy_with_outflow": "主力资金流出与买入结论冲突，买点需等待支撑确认或资金回流。",
            "sell_near_support": "价格贴近支撑且未见资金持续流出，不宜仅因单日下跌直接卖出。",
            "sell_with_inflow": "主力资金流入与卖出结论冲突，先按持有观察处理并跟踪支撑失效。",
            "hold_shakeout": "价格回落至支撑附近但资金未确认流出，更适合按洗盘观察处理。",
            "hold_mid_range": "价格处于支撑与压力之间且资金流不明确，维持震荡观望更可操作。",
        },
        "en": {
            "buy_near_resistance": "Price is near resistance without confirmed main-force inflow, so chasing the rebound is not actionable.",
            "buy_with_outflow": "Main-force outflow conflicts with a buy call; wait for support confirmation or capital inflow.",
            "sell_near_support": "Price is near support without sustained outflow, so a one-day drop is not enough to sell.",
            "sell_with_inflow": "Main-force inflow conflicts with a sell call; hold and watch for support failure.",
            "hold_shakeout": "Price pulled back near support without confirmed outflow, which is better treated as a shakeout watch.",
            "hold_mid_range": "Price is between support and resistance with neutral fund flow, so range-bound watch is more actionable.",
        },
    }
    reason = reason_templates[language].get(reason_key, "")
    result.operation_advice = advice
    if language == "zh" and "震荡" not in str(result.trend_prediction) and advice_key == "range":
        result.trend_prediction = "震荡"
    elif language == "en" and advice_key == "range":
        result.trend_prediction = "Sideways"

    dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}
    result.dashboard = dashboard
    core = dashboard.get("core_conclusion")
    if not isinstance(core, dict):
        core = {}
        dashboard["core_conclusion"] = core
    core["signal_type"] = "🟡持有观望" if language == "zh" else "🟡 Hold / Watch"
    core["one_sentence"] = f"{advice}：{reason}" if language == "zh" else f"{advice}: {reason}"
    position_advice = core.get("position_advice")
    if not isinstance(position_advice, dict):
        position_advice = {}
        core["position_advice"] = position_advice
    if language == "zh":
        position_advice["no_position"] = "空仓先不追涨杀跌，等待支撑确认、放量突破或资金回流后再行动。"
        position_advice["has_position"] = "持仓以关键支撑为风控线，未跌破前以观察和分批控仓为主。"
    else:
        position_advice["no_position"] = "Do not chase or panic; wait for support confirmation, breakout, or renewed inflow."
        position_advice["has_position"] = "Use key support as the risk line and manage position size unless support fails."

    dashboard["decision_stability"] = {
        "applied": True,
        "reason": reason,
        "current_price": current_price,
        "support": support,
        "resistance": resistance,
        "capital_flow_bias": flow_bias,
    }
    if reason and reason not in str(result.risk_warning or ""):
        sep = "；" if language == "zh" else "; "
        result.risk_warning = f"{result.risk_warning}{sep}{reason}" if result.risk_warning else reason
    result.buy_reason = reason or result.buy_reason
    logger.info("[decision_stability] Applied structural hold calibration: %s", reason_key)
