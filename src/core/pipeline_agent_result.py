# -*- coding: utf-8 -*-
"""Agent-result to AnalysisResult conversion and trend fallbacks.

Split out of :mod:`src.core.pipeline` to keep the pipeline class focused on
orchestration. Methods rely on ``self`` state from
:class:`src.core.pipeline.StockAnalysisPipeline`.
"""

import logging
from typing import Any, Dict, List, Optional

from src.analysis.stock_report_analyzer import AnalysisResult
from src.data.stock_mapping import STOCK_NAME_MAP
from src.enums import ReportType
from src.report_language import (
    get_unknown_text,
    infer_decision_type_from_advice,
    localize_confidence_level,
    localize_operation_advice,
    localize_trend_prediction,
    normalize_report_language,
)
from src.stock_analyzer import TrendAnalysisResult

logger = logging.getLogger(__name__)


class AgentResultMixin:
    """Agent-result conversion and trend-based fallbacks for the pipeline."""

    def _agent_result_to_analysis_result(
        self,
        agent_result,
        code: str,
        stock_name: str,
        report_type: ReportType,
        query_id: str,
        trend_result: Optional[TrendAnalysisResult] = None,
    ) -> AnalysisResult:
        """
        将 AgentResult 转换为 AnalysisResult。
        """
        report_language = normalize_report_language(getattr(self.config, "report_language", "zh"))
        result = AnalysisResult(
            code=code,
            name=stock_name,
            sentiment_score=50,
            trend_prediction="Unknown" if report_language == "en" else "未知",
            operation_advice="Watch" if report_language == "en" else "观望",
            confidence_level=localize_confidence_level("medium", report_language),
            report_language=report_language,
            success=agent_result.success,
            error_message=agent_result.error or None,
            data_sources=f"agent:{agent_result.provider}",
            model_used=agent_result.model or None,
        )

        if agent_result.success and agent_result.dashboard:
            dash = agent_result.dashboard
            ai_stock_name = str(dash.get("stock_name", "")).strip()
            if ai_stock_name and self._is_placeholder_stock_name(stock_name, code):
                result.name = ai_stock_name

            nested_dashboard = dash.get("dashboard") if isinstance(dash, dict) else None

            raw_score = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "sentiment_score",
                scalar=True,
            )
            if self._is_agent_field_missing(raw_score, scalar=True):
                fallback_score = self._trend_score_fallback(trend_result)
                if fallback_score is not None:
                    result.sentiment_score = fallback_score
                    self._mark_trend_fallback_source(result)
            else:
                result.sentiment_score = self._safe_int(raw_score, 50)

            raw_trend = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "trend_prediction",
                scalar=True,
                expect_text=True,
            )
            if self._is_agent_field_missing(raw_trend, scalar=True, expect_text=True):
                trend_label = self._trend_label_fallback(
                    trend_result,
                    report_language,
                )
                if trend_label:
                    result.trend_prediction = trend_label
                    self._mark_trend_fallback_source(result)
            else:
                result.trend_prediction = str(raw_trend)

            raw_advice = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "operation_advice",
                scalar=True,
                allow_dict=True,
                expect_text=True,
            )
            extracted_advice = ""
            if isinstance(raw_advice, dict):
                # LLM may return {"no_position": "...", "has_position": "..."}
                extracted_advice = self._extract_advice_text_from_dict(raw_advice)
                if extracted_advice:
                    result.operation_advice = localize_operation_advice(
                        extracted_advice,
                        report_language,
                    )
                else:
                    signal_label = self._trend_signal_fallback(
                        trend_result,
                        report_language,
                    )
                    if signal_label:
                        result.operation_advice = signal_label
                        self._mark_trend_fallback_source(result)
            elif not self._is_agent_field_missing(
                raw_advice,
                scalar=True,
                allow_dict=True,
                expect_text=True,
            ):
                result.operation_advice = str(raw_advice) if raw_advice else ("Watch" if report_language == "en" else "观望")
            else:
                signal_label = self._trend_signal_fallback(trend_result, report_language)
                if signal_label:
                    result.operation_advice = signal_label
                    self._mark_trend_fallback_source(result)
            from src.agent.protocols import normalize_decision_signal

            raw_decision = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "decision_type",
                scalar=True,
                expect_text=True,
            )
            if self._is_agent_field_missing(raw_decision, scalar=True, expect_text=True):
                trend_decision = self._trend_decision_fallback(trend_result)
                decision_from_advice = infer_decision_type_from_advice(
                    result.operation_advice,
                    default="",
                )
                if decision_from_advice:
                    result.decision_type = decision_from_advice
                    if (
                        self._is_agent_field_missing(
                            raw_advice,
                            scalar=True,
                            allow_dict=True,
                            expect_text=True,
                        )
                        and not extracted_advice
                        and trend_decision
                    ):
                        self._mark_trend_fallback_source(result)
                else:
                    result.decision_type = trend_decision or "hold"
                    if trend_decision:
                        self._mark_trend_fallback_source(result)
            else:
                result.decision_type = normalize_decision_signal(raw_decision)
            result.confidence_level = localize_confidence_level(
                self._agent_dashboard_value(dash, nested_dashboard, "confidence_level")
                or result.confidence_level,
                report_language,
            )
            raw_summary = self._agent_dashboard_value(
                dash,
                nested_dashboard,
                "analysis_summary",
                scalar=True,
                expect_text=True,
            )
            if not self._is_agent_field_missing(raw_summary, scalar=True, expect_text=True):
                result.analysis_summary = str(raw_summary)
            else:
                result.analysis_summary = self._summary_fallback_from_result(result, report_language)
            # The AI returns a top-level dict that contains a nested 'dashboard' sub-key
            # with core_conclusion / battle_plan / intelligence.  AnalysisResult's helper
            # methods (get_sniper_points, get_core_conclusion, etc.) expect that inner
            # structure, so we unwrap it here.
            result.dashboard = nested_dashboard or dash
            self._backfill_agent_dashboard_fields(result, trend_result, report_language)
        else:
            self._apply_trend_fallback(result, trend_result, report_language)
            if trend_result is not None:
                result.analysis_summary = (
                    result.analysis_summary
                    or self._summary_fallback_from_result(result, report_language)
                )
                self._backfill_agent_dashboard_fields(result, trend_result, report_language)
            if not result.error_message:
                result.error_message = "Agent failed to generate a valid decision dashboard" if report_language == "en" else "Agent 未能生成有效的决策仪表盘"

        return result

    @staticmethod
    def _agent_dashboard_value(
        dash: Dict[str, Any],
        nested_dashboard: Any,
        key: str,
        *,
        scalar: bool = False,
        allow_dict: bool = False,
        expect_text: bool = False,
    ) -> Any:
        """Read a scalar from top-level agent payload, then nested dashboard fallback."""
        value = dash.get(key) if isinstance(dash, dict) else None
        if isinstance(nested_dashboard, dict) and AgentResultMixin._is_agent_field_missing(
            value,
            scalar=scalar,
            allow_dict=allow_dict,
            expect_text=expect_text,
        ):
            nested_value = nested_dashboard.get(key)
            if not AgentResultMixin._is_agent_field_missing(
                nested_value,
                scalar=scalar,
                allow_dict=allow_dict,
                expect_text=expect_text,
            ):
                value = nested_value
        return value

    @staticmethod
    def _extract_advice_text_from_dict(raw_advice: dict) -> str:
        for field in ("has_position", "no_position"):
            if isinstance(raw_advice.get(field), str):
                text = raw_advice[field].strip()
                if not AgentResultMixin._is_agent_placeholder_text(text):
                    return text

        for value in raw_advice.values():
            if isinstance(value, str):
                text = value.strip()
                if not AgentResultMixin._is_agent_placeholder_text(text):
                    return text

        return ""

    @staticmethod
    def _is_agent_placeholder_text(text: str) -> bool:
        if not text:
            return True
        return text.lower() in {"n/a", "na", "none", "null", "unknown", "tbd"} or text in {
            "未知",
            "待补充",
            "数据缺失",
            "无",
        }

    @staticmethod
    def _is_agent_field_missing(
        value: Any,
        *,
        scalar: bool = False,
        allow_dict: bool = False,
        expect_text: bool = False,
    ) -> bool:
        if scalar and isinstance(value, dict):
            if not allow_dict or not value:
                return True
            return not AgentResultMixin._extract_advice_text_from_dict(value)
        if value is None:
            return True
        if expect_text and scalar:
            if not isinstance(value, str):
                return True
        if isinstance(value, str):
            text = value.strip()
            return AgentResultMixin._is_agent_placeholder_text(text)
        if isinstance(value, dict):
            if scalar:
                return not allow_dict
            return not value
        if scalar and isinstance(value, (list, tuple, set)):
            return True
        return False

    @staticmethod
    def _trend_score_fallback(trend_result: Optional[TrendAnalysisResult]) -> Optional[int]:
        if trend_result is None:
            return None
        try:
            score = int(getattr(trend_result, "signal_score", 0))
        except (TypeError, ValueError):
            return None
        return score if score > 0 else None

    @staticmethod
    def _trend_label_fallback(
        trend_result: Optional[TrendAnalysisResult],
        report_language: str = "zh",
    ) -> str:
        if trend_result is None:
            return ""
        trend_status = getattr(trend_result, "trend_status", None)
        value = getattr(trend_status, "value", None) or str(trend_status or "").strip()
        if report_language != "en":
            return value
        return localize_trend_prediction(value, report_language)

    @staticmethod
    def _trend_signal_fallback(
        trend_result: Optional[TrendAnalysisResult],
        report_language: str = "zh",
    ) -> str:
        if trend_result is None:
            return ""
        buy_signal = getattr(trend_result, "buy_signal", None)
        value = getattr(buy_signal, "value", None) or str(buy_signal or "").strip()
        return localize_operation_advice(value, report_language)

    @staticmethod
    def _trend_decision_fallback(trend_result: Optional[TrendAnalysisResult]) -> Optional[str]:
        if trend_result is None:
            return None
        signal_name = getattr(getattr(trend_result, "buy_signal", None), "name", "").lower()
        return {
            "strong_buy": "buy",
            "buy": "buy",
            "hold": "hold",
            "wait": "hold",
            "sell": "sell",
            "strong_sell": "sell",
        }.get(signal_name)

    @staticmethod
    def _mark_trend_fallback_source(result: AnalysisResult) -> None:
        if "trend:fallback" in (result.data_sources or ""):
            return
        result.data_sources = (
            f"{result.data_sources},trend:fallback"
            if result.data_sources
            else "trend:fallback"
        )

    @staticmethod
    def _summary_fallback_from_result(result: AnalysisResult, report_language: str) -> str:
        trend = (result.trend_prediction or "").strip()
        advice = (result.operation_advice or "").strip()
        if trend and advice:
            if report_language == "en":
                return f"Trend view: {trend}; action advice: {advice}."
            return f"趋势结论：{trend}；操作建议：{advice}。"
        return ""

    def _backfill_agent_dashboard_fields(
        self,
        result: AnalysisResult,
        trend_result: Optional[TrendAnalysisResult],
        report_language: str,
    ) -> None:
        if not isinstance(result.dashboard, dict):
            result.dashboard = {}
        dashboard = result.dashboard

        for key in (
            "sentiment_score",
            "trend_prediction",
            "operation_advice",
            "decision_type",
            "confidence_level",
            "analysis_summary",
        ):
            current = dashboard.get(key)
            if key == "sentiment_score":
                if self._is_agent_field_missing(current, scalar=True):
                    dashboard[key] = getattr(result, key)
            elif self._is_agent_field_missing(current, scalar=True, expect_text=True):
                dashboard[key] = getattr(result, key)

        core = dashboard.get("core_conclusion")
        if not isinstance(core, dict):
            core = {}
            dashboard["core_conclusion"] = core
        if self._is_agent_field_missing(core.get("one_sentence"), scalar=True):
            core["one_sentence"] = result.analysis_summary or self._summary_fallback_from_result(
                result,
                report_language,
            ) or ("Analysis pending" if report_language == "en" else "分析待补充")

        intelligence = dashboard.get("intelligence")
        if not isinstance(intelligence, dict):
            intelligence = {}
            dashboard["intelligence"] = intelligence
        risk_alerts = intelligence.get("risk_alerts")
        if (
            "risk_alerts" not in intelligence
            or self._is_agent_field_missing(risk_alerts)
            or not isinstance(risk_alerts, list)
        ):
            risk_factors = getattr(trend_result, "risk_factors", None) or []
            intelligence["risk_alerts"] = list(risk_factors)

        if result.decision_type in ("buy", "hold"):
            battle = dashboard.get("battle_plan")
            if not isinstance(battle, dict):
                battle = {}
                dashboard["battle_plan"] = battle
            sniper_points = battle.get("sniper_points")
            if not isinstance(sniper_points, dict):
                sniper_points = {}
                battle["sniper_points"] = sniper_points
            if self._is_agent_field_missing(sniper_points.get("stop_loss"), scalar=True):
                sniper_points["stop_loss"] = self._stop_loss_fallback_from_trend(
                    trend_result,
                    report_language,
                )

    @staticmethod
    def _stop_loss_fallback_from_trend(
        trend_result: Optional[TrendAnalysisResult],
        report_language: str,
    ) -> Any:
        levels = getattr(trend_result, "support_levels", None) if trend_result else None
        if levels:
            return levels[0]
        return "To be completed" if report_language == "en" else "待补充"

    @staticmethod
    def _apply_trend_fallback(
        result: AnalysisResult,
        trend_result: Optional[TrendAnalysisResult],
        report_language: str,
    ) -> None:
        if trend_result is None:
            result.sentiment_score = 50
            result.operation_advice = "Watch" if report_language == "en" else "观望"
            return

        score = getattr(trend_result, "signal_score", None)
        try:
            numeric_score = int(score)
        except (TypeError, ValueError):
            numeric_score = 50
        result.sentiment_score = numeric_score if numeric_score > 0 else 50

        trend_label = AgentResultMixin._trend_label_fallback(trend_result, report_language)
        if trend_label:
            result.trend_prediction = trend_label

        buy_signal = getattr(trend_result, "buy_signal", None)
        signal_label = AgentResultMixin._trend_signal_fallback(
            trend_result,
            report_language,
        )
        if signal_label:
            result.operation_advice = signal_label
        else:
            result.operation_advice = "Watch" if report_language == "en" else "观望"

        from src.agent.protocols import normalize_decision_signal

        signal_name = getattr(buy_signal, "name", "").lower()
        signal_to_decision = {
            "strong_buy": "buy",
            "buy": "buy",
            "hold": "hold",
            "wait": "hold",
            "sell": "sell",
            "strong_sell": "sell",
        }
        result.decision_type = signal_to_decision.get(signal_name, result.decision_type or "hold")
        result.decision_type = normalize_decision_signal(result.decision_type)
        result.data_sources = f"{result.data_sources},trend:fallback" if result.data_sources else "trend:fallback"

    @staticmethod
    def _is_placeholder_stock_name(name: str, code: str) -> bool:
        """Return True when the stock name is missing or placeholder-like."""
        if not name:
            return True
        normalized = str(name).strip()
        if not normalized:
            return True
        if normalized == code:
            return True
        if normalized.startswith("股票"):
            return True
        if "Unknown" in normalized:
            return True
        return False

