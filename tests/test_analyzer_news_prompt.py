# -*- coding: utf-8 -*-
"""Tests for analyzer evidence constraints and technical consistency."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from finance_analysis.analysis.stock_report_analyzer import (
    StockReportAnalyzer,
    _BULLISH_TREND_HINTS,
    _contains_trend_hint,
    _infer_trend_direction,
    _sanitize_trend_analysis_for_prompt,
)


class AnalyzerNewsPromptTestCase(unittest.TestCase):
    def test_contains_trend_hint_treats_non_adjacent_negation_as_negated(self) -> None:
        self.assertFalse(_contains_trend_hint("尚未形成上升趋势，继续观察。", _BULLISH_TREND_HINTS))
        self.assertFalse(_contains_trend_hint("未形成上升趋势，继续观察。", _BULLISH_TREND_HINTS))
        self.assertFalse(_contains_trend_hint("并未形成上升趋势，继续观察。", _BULLISH_TREND_HINTS))
        self.assertFalse(_contains_trend_hint("没有形成多头排列，继续观察。", _BULLISH_TREND_HINTS))
        self.assertFalse(_contains_trend_hint("当前无多头排列，仍需观察。", _BULLISH_TREND_HINTS))
        self.assertFalse(_contains_trend_hint("尚不属于上升趋势，反弹仍待确认。", _BULLISH_TREND_HINTS))
        self.assertFalse(_contains_trend_hint("当前非多头排列，仍需观察。", _BULLISH_TREND_HINTS))
        self.assertFalse(_contains_trend_hint("This is not a bullish trend yet.", _BULLISH_TREND_HINTS))

    def test_contains_trend_hint_scans_later_non_negated_occurrences(self) -> None:
        self.assertTrue(
            _contains_trend_hint(
                "不是多头排列，后续放量后再次出现多头排列信号。",
                _BULLISH_TREND_HINTS,
            )
        )

    def test_contains_trend_hint_keeps_contrast_clause_target_hint(self) -> None:
        self.assertTrue(_contains_trend_hint("不是空头而是多头排列，趋势修复。", _BULLISH_TREND_HINTS))
        self.assertFalse(_contains_trend_hint("未转为上升趋势，反弹仍待确认。", _BULLISH_TREND_HINTS))

    def test_contains_trend_hint_ignores_single_character_prefixes_in_common_words(self) -> None:
        self.assertTrue(_contains_trend_hint("非常明显的多头排列，趋势仍在延续。", _BULLISH_TREND_HINTS))
        self.assertTrue(_contains_trend_hint("未来上升趋势若放量将进一步确认。", _BULLISH_TREND_HINTS))
        self.assertEqual(
            _infer_trend_direction({"trend_status": "非常明显的多头排列", "ma_alignment": "未来上升趋势逐步明确"}),
            "bullish",
        )

    def test_infer_trend_direction_recognizes_weak_bullish_and_bearish_states(self) -> None:
        self.assertEqual(
            _infer_trend_direction({"trend_status": "弱势多头", "ma_alignment": "弱势多头，MA5>MA10 但 MA10≤MA20"}),
            "bullish",
        )
        self.assertEqual(
            _infer_trend_direction({"trend_status": "弱势空头", "ma_alignment": "弱势空头，MA5<MA10 但 MA10≥MA20"}),
            "bearish",
        )

    def test_infer_trend_direction_ignores_negated_bullish_hints(self) -> None:
        self.assertEqual(
            _infer_trend_direction({"trend_status": "未形成上升趋势", "ma_alignment": "当前非多头排列"}),
            "neutral",
        )
        self.assertEqual(
            _infer_trend_direction({"trend_status": "没有形成多头排列", "ma_alignment": "当前无上升趋势"}),
            "neutral",
        )

    def test_infer_trend_direction_keeps_contrast_clause_final_direction(self) -> None:
        self.assertEqual(
            _infer_trend_direction({"trend_status": "不是空头而是多头排列", "ma_alignment": ""}),
            "bullish",
        )


    def test_analysis_prompt_contains_actionability_guardrails(self) -> None:
        with patch("finance_analysis.analysis.stock_report_analyzer.get_pipeline_config"):
            analyzer = StockReportAnalyzer()

        prompt = analyzer._get_analysis_system_prompt("zh", stock_code="002812")

        self.assertIn("可操作性与稳定性约束", prompt)
        self.assertIn("不得仅因为单日涨跌", prompt)
        self.assertIn("支撑/压力位", prompt)
        self.assertIn("洗盘观察", prompt)


    def test_prompt_includes_capital_flow_as_operation_filter(self) -> None:
        with patch("finance_analysis.analysis.stock_report_analyzer.get_pipeline_config"):
            analyzer = StockReportAnalyzer()

        context = {
            "code": "002812",
            "stock_name": "恩捷股份",
            "date": "2026-04-01",
            "today": {"close": 32.8, "ma5": 31.2, "ma10": 30.5, "ma20": 29.8},
            "fundamental_context": {
                "capital_flow": {
                    "status": "ok",
                    "data": {
                        "stock_flow": {
                            "main_net_inflow": -1200000,
                            "inflow_5d": -3600000,
                            "inflow_10d": -5200000,
                        },
                        "sector_rankings": {
                            "top": [{"name": "电池"}],
                            "bottom": [{"name": "化工"}],
                        },
                    },
                }
            },
        }

        prompt = analyzer._format_prompt(context, "恩捷股份")

        self.assertIn("主力资金流向（操作建议过滤器）", prompt)
        self.assertIn("主力净流入", prompt)
        self.assertIn("-1200000", prompt)
        self.assertIn("接近压力且主力流出时不得追买", prompt)
        self.assertIn("洗盘观察", prompt)


    def test_format_prompt_removes_bullish_reasons_when_final_trend_is_bearish(self) -> None:
        with patch("finance_analysis.analysis.stock_report_analyzer.get_pipeline_config"):
            analyzer = StockReportAnalyzer(

            )

        context = {
            "code": "603259",
            "stock_name": "药明康德",
            "date": "2026-04-28",
            "today": {"close": 58.6, "ma5": 57.2, "ma10": 58.8, "ma20": 60.4},
            "yesterday": {"close": 57.8},
            "volume_change_ratio": 12.4,
            "trend_analysis": {
                "trend_status": "空头排列",
                "ma_alignment": "空头排列 MA5<MA10<MA20",
                "trend_strength": 34,
                "bias_ma5": 2.1,
                "bias_ma10": -0.8,
                "volume_status": "放量",
                "volume_trend": "放量震荡",
                "buy_signal": "观察",
                "signal_score": 41,
                "signal_reasons": ["多头排列，持续上涨", "事件催化存在但技术待确认"],
                "risk_factors": ["跌破MA20，趋势承压"],
            },
        }

        prompt = analyzer._format_prompt(
            context,
            "药明康德",
        )

        self.assertIn("空头排列 MA5<MA10<MA20", prompt)
        self.assertNotIn("多头排列，持续上涨", prompt)
        self.assertIn("事件催化存在但技术待确认", prompt)
        self.assertIn("事件先行、技术待确认", prompt)
        self.assertIn("量能异常提示", prompt)
        self.assertIn("技术面一致性", prompt)

    def test_format_prompt_removes_bearish_risks_when_final_trend_is_bullish(self) -> None:
        with patch("finance_analysis.analysis.stock_report_analyzer.get_pipeline_config"):
            analyzer = StockReportAnalyzer(

            )

        context = {
            "code": "600519",
            "stock_name": "贵州茅台",
            "date": "2026-04-28",
            "today": {"close": 1688.0, "ma5": 1675.0, "ma10": 1660.0, "ma20": 1640.0},
            "trend_analysis": {
                "trend_status": "多头排列",
                "ma_alignment": "多头排列 MA5>MA10>MA20",
                "trend_strength": 78,
                "bias_ma5": 1.8,
                "bias_ma10": 3.2,
                "volume_status": "平量",
                "volume_trend": "量价配合",
                "buy_signal": "偏强",
                "signal_score": 73,
                "signal_reasons": ["多头排列，持续上涨", "空头排列，持续下跌"],
                "risk_factors": ["空头排列，持续下跌", "财报披露前波动可能放大"],
            },
        }

        prompt = analyzer._format_prompt(context, "贵州茅台")

        self.assertIn("多头排列 MA5>MA10>MA20", prompt)
        self.assertIn("财报披露前波动可能放大", prompt)
        self.assertNotIn("空头排列，持续下跌\n", prompt)
        self.assertNotIn("空头排列，持续下跌", prompt)
        self.assertIn("已剔除与多头主判断直接冲突的空头结构理由", prompt)
        self.assertIn("已剔除与多头主判断直接冲突的空头结构风险表述", prompt)

    def test_format_prompt_removes_bullish_reasons_when_final_trend_is_weak_bearish(self) -> None:
        with patch("finance_analysis.analysis.stock_report_analyzer.get_pipeline_config"):
            analyzer = StockReportAnalyzer(

            )

        context = {
            "code": "300750",
            "stock_name": "宁德时代",
            "date": "2026-04-28",
            "today": {"close": 178.5, "ma5": 176.0, "ma10": 180.2, "ma20": 179.9},
            "trend_analysis": {
                "trend_status": "弱势空头",
                "ma_alignment": "弱势空头，MA5<MA10 但 MA10≥MA20",
                "trend_strength": 43,
                "bias_ma5": 1.4,
                "bias_ma10": -0.9,
                "volume_status": "平量",
                "volume_trend": "量能一般",
                "buy_signal": "观察",
                "signal_score": 45,
                "signal_reasons": ["弱势多头修复", "多头排列，持续上涨", "事件催化存在但技术待确认"],
                "risk_factors": ["MA10 压制仍在"],
            },
        }

        prompt = analyzer._format_prompt(
            context,
            "宁德时代",
        )

        self.assertIn("弱势空头，MA5<MA10 但 MA10≥MA20", prompt)
        self.assertNotIn("弱势多头修复", prompt)
        self.assertNotIn("多头排列，持续上涨", prompt)
        self.assertIn("事件催化存在但技术待确认", prompt)
        self.assertIn("已剔除与空头主判断直接冲突的看多结构理由", prompt)

    def test_sanitize_trend_analysis_for_prompt_returns_derived_copy_only(self) -> None:
        original = {
            "trend_status": "空头排列",
            "ma_alignment": "空头排列 MA5<MA10<MA20",
            "signal_reasons": ["多头排列，持续上涨", "事件催化存在但技术待确认"],
            "risk_factors": ["跌破MA20，趋势承压"],
        }

        sanitized = _sanitize_trend_analysis_for_prompt(original, volume_change_ratio=12.4)

        self.assertEqual(
            original["signal_reasons"],
            ["多头排列，持续上涨", "事件催化存在但技术待确认"],
        )
        self.assertNotIn("prompt_consistency_notes", original)
        self.assertNotIn("prompt_trend_direction", original)
        self.assertNotIn("多头排列，持续上涨", sanitized["signal_reasons"])
        self.assertEqual(sanitized["prompt_trend_direction"], "bearish")


if __name__ == "__main__":
    unittest.main()


def test_prompt_limits_claims_to_supplied_evidence():
    analyzer = StockReportAnalyzer(config=SimpleNamespace(report_language="zh"))
    context = {"code": "AAPL.US", "stock_name": "Apple", "date": "2026-09-15", "today": {}, "data_missing": True}
    prompt = analyzer._format_prompt(context, "Apple")

    assert "禁止编造新闻、公告、评级或目标价" in prompt
    assert "数据缺失，无法判断" in prompt
    system_prompt = analyzer._get_analysis_system_prompt("zh", "AAPL.US")
    assert "缺失时说明无法判断" in system_prompt
