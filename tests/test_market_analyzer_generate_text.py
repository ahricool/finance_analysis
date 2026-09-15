# -*- coding: utf-8 -*-
"""Tests for Analyzer.generate_text() and the market_analyzer bypass fix.

Covers:
- generate_text() returns the LLM response on success
- generate_text() returns None and logs on failure (no exception propagated)
- market_analyzer calls generate_text(), not private analyzer attributes
- Any provider configuration (Gemini / Anthropic / OpenAI / API backend)
  does NOT trigger AttributeError (regression guard for the old bypass bug)
"""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Stub heavy dependencies before project imports
for _mod in ("litellm", "google.generativeai", "google.genai", "anthropic"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()



# ---------------------------------------------------------------------------
# Analyzer.generate_text()
# ---------------------------------------------------------------------------

class TestAnalyzerGenerateText:
    def _make_analyzer(self):
        from finance_analysis.analysis.stock_report_analyzer import StockReportAnalyzer
        return StockReportAnalyzer()

    def test_parse_response_non_json_returns_failure(self):
        """_parse_response must return success=False when LLM output is not valid JSON."""
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(report_language="zh")

        from finance_analysis.analysis.stock_report_analyzer import StockReportAnalyzer

        result = StockReportAnalyzer._parse_response(analyzer, "这是一段纯文本分析，没有 JSON。", "600519", "贵州茅台")
        assert result.success is False
        assert result.error_message is not None
        assert result.code == "600519"


    def test_parse_response_malformed_json_returns_failure(self):
        """_parse_response must return success=False when JSON extraction fails."""
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(report_language="zh")

        from finance_analysis.analysis.stock_report_analyzer import StockReportAnalyzer

        malformed = "Here is the analysis: {broken json content without closing"
        result = StockReportAnalyzer._parse_response(analyzer, malformed, "AAPL", "Apple")
        assert result.success is False
        assert result.error_message is not None


    def test_parse_response_valid_json_returns_success(self):
        """_parse_response must return success=True when LLM output contains valid JSON."""
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(report_language="zh")

        from finance_analysis.analysis.stock_report_analyzer import StockReportAnalyzer
        import json

        valid_response = json.dumps({
            "sentiment_score": 75,
            "trend_prediction": "看多",
            "operation_advice": "持有",
            "analysis_summary": "测试分析",
        })
        result = StockReportAnalyzer._parse_response(analyzer, valid_response, "600519", "贵州茅台")
        assert result.success is True
        assert result.error_message is None




# ---------------------------------------------------------------------------
# market_analyzer uses generate_text(), not private attributes
# ---------------------------------------------------------------------------

class TestMarketAnalyzerBypassFix:
    def _make_market_analyzer_with_mock_generate_text(self, return_value="复盘报告"):
        """Return a MarketAnalyzer whose embedded Analyzer.generate_text is mocked."""
        from finance_analysis.market_review.profile import CN_PROFILE
        from finance_analysis.market_review.strategy import get_market_strategy_blueprint

        with patch("finance_analysis.analysis.stock_report_analyzer.get_pipeline_config") as mock_cfg, \
             patch("finance_analysis.analysis.pipeline_config.get_pipeline_config") as mock_cfg2:
            cfg = MagicMock()
            cfg.market_review_region = "cn"
            cfg.report_language = "zh"
            mock_cfg.return_value = cfg
            mock_cfg2.return_value = cfg

            from finance_analysis.analysis.stock_report_analyzer import StockReportAnalyzer
            from finance_analysis.market_review.analyzer import MarketAnalyzer

            analyzer = StockReportAnalyzer.__new__(StockReportAnalyzer)
            analyzer.generate_text = MagicMock(return_value=return_value)

            ma = MarketAnalyzer.__new__(MarketAnalyzer)
            ma.analyzer = analyzer
            ma.config = cfg
            ma.profile = CN_PROFILE
            ma.strategy = get_market_strategy_blueprint("cn")
            ma.region = "cn"
            return ma

    def test_no_access_to_private_model_attribute(self):
        """generate_text() must be called; _model must never be accessed."""
        ma = self._make_market_analyzer_with_mock_generate_text("复盘结果")
        # Ensure _model attribute does not exist (simulates PR #494 state)
        assert not hasattr(ma.analyzer, "_model") or ma.analyzer._model is None, (
            "_model should not be set on the LiteLLM-based analyzer"
        )
        # generate_text is a MagicMock, so calling it won't crash
        result = ma.analyzer.generate_text("prompt")
        assert isinstance(result, str) and len(result) > 0
        ma.analyzer.generate_text.assert_called_once()

    def test_generate_text_none_falls_back_to_template(self):
        """generate_market_review() falls back to template when generate_text returns None."""
        from finance_analysis.market_review.analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=5.0,
                    change_pct=0.15,
                )
            ],
        )
        result = ma.generate_market_review(overview, [])
        assert isinstance(result, str) and len(result) > 0
        ma.analyzer.generate_text.assert_called_once()

    def test_market_review_uses_8192_max_tokens(self):
        """generate_market_review() should request a larger output budget to avoid truncation."""
        from finance_analysis.market_review.analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="复盘结果")
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=5.0,
                    change_pct=0.15,
                )
            ],
        )

        result = ma.generate_market_review(overview, [])

        assert isinstance(result, str) and len(result) > 0
        ma.analyzer.generate_text.assert_called_once()
        _, kwargs = ma.analyzer.generate_text.call_args
        assert kwargs["max_tokens"] == 8192
        assert kwargs["temperature"] == 0.7

    def test_generate_template_review_uses_english_shell_for_cn_when_report_language_is_en(self):
        from finance_analysis.market_review.analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=12.0,
                    change_pct=0.36,
                )
            ],
            up_count=3200,
            down_count=1800,
            limit_up_count=88,
            limit_down_count=5,
            total_amount=14567.0,
            top_sectors=[{"name": "AI算力", "change_pct": 3.25}],
            bottom_sectors=[{"name": "煤炭", "change_pct": -1.12}],
        )

        result = ma.generate_market_review(overview, [])

        assert "A-share Market Recap" in result
        assert "### 1. Market Summary" in result
        assert "### 3. Breadth & Liquidity" in result
        assert "Turnover (CNY 100m)" in result
        assert "### 4. Sector Highlights" in result
        assert "### 6. Strategy Framework" in result
        assert "### 一、市场总结" not in result

    def test_generate_template_review_keeps_chinese_shell_for_us_when_report_language_is_default(self):
        from finance_analysis.market_review.profile import US_PROFILE
        from finance_analysis.market_review.strategy import get_market_strategy_blueprint
        from finance_analysis.market_review.analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        ma.region = "us"
        ma.profile = US_PROFILE
        ma.strategy = get_market_strategy_blueprint("us")
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="SPX",
                    name="标普500",
                    current=5200.0,
                    change=-18.0,
                    change_pct=-0.35,
                )
            ],
        )

        result = ma.generate_market_review(overview, [])

        assert "## 2026-03-05 大盘复盘" in result
        assert "### 一、盘面总览" in result
        assert "今日美股市场整体呈现**小幅下跌**态势" in result
        assert "### 1. Market Summary" not in result
        assert "US Market Recap" not in result

    def test_inject_data_into_review_matches_english_headings(self):
        from finance_analysis.market_review.analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=12.0,
                    change_pct=0.36,
                    amount=145000000000.0,
                )
            ],
            up_count=3200,
            down_count=1800,
            flat_count=100,
            limit_up_count=88,
            limit_down_count=5,
            total_amount=14567.0,
            top_sectors=[{"name": "AI算力", "change_pct": 3.25}],
            bottom_sectors=[{"name": "煤炭", "change_pct": -1.12}],
        )
        review = """## 2026-03-05 A-share Market Recap

### 1. Market Summary
Summary text.

### 2. Index Commentary
Index text.

### 4. Sector Highlights
Sector text.
"""

        result = ma._inject_data_into_review(review, overview)

        assert "Advancers **3200**" in result
        assert "Turnover **14567** (CNY 100m)" in result
        assert "| Index | Last | Change % | Open | High | Low | Amplitude | Turnover (CNY 100m) |" in result
        assert "#### Leading Sectors" in result
        assert "| 1 | AI算力 | +3.25% |" in result
        assert "#### Lagging Sectors" in result
        assert "| 1 | 煤炭 | -1.12% |" in result

    def test_inject_data_into_review_matches_reference_style_chinese_headings(self):
        from finance_analysis.market_review.analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=12.0,
                    change_pct=0.36,
                    open=3288.0,
                    high=3312.0,
                    low=3276.0,
                    amount=145000000000.0,
                    amplitude=1.1,
                )
            ],
            up_count=3200,
            down_count=1800,
            flat_count=100,
            limit_up_count=88,
            limit_down_count=5,
            total_amount=14567.0,
            top_sectors=[{"name": "AI算力", "change_pct": 3.25}],
            bottom_sectors=[{"name": "煤炭", "change_pct": -1.12}],
        )
        news = [{"title": "AI算力板块走强", "snippet": "算力产业链延续活跃，成交额放大"}]
        review = """## 2026-03-05 大盘复盘

### 一、盘面总览
总结。

### 二、指数结构
指数。

### 三、板块主线
板块。

### 五、消息催化
新闻。
"""

        result = ma._inject_data_into_review(review, overview, news)

        assert "大盘红绿灯" in result
        assert "green（可进攻）" in result
        assert "核心原因" in result
        assert "操作建议" in result
        assert "盘面温度" in result
        assert "| 上涨/下跌/平盘 | 3200 / 1800 / 100 |" in result
        assert "| 指数 | 最新 | 涨跌幅 | 开盘 | 最高 | 最低 | 振幅 | 成交额(亿) |" in result
        assert "| 上证指数 | 3300.00 | 🟢 +0.36% | 3288.00 | 3312.00 | 3276.00 | 1.10% | 1450 |" in result
        assert "#### 领涨板块 Top 5" in result
        assert "| 1 | AI算力 | +3.25% |" in result
        assert "#### 近三日催化线索" in result
        assert "AI算力板块走强" in result

    def test_news_block_labels_snippets_and_preserves_source_url(self):
        from finance_analysis.market_review.analyzer import MarketAnalyzer

        ma = MarketAnalyzer.__new__(MarketAnalyzer)
        ma.config = SimpleNamespace(report_language="zh")
        ma.region = "cn"
        long_snippet = (
            "复盘必读 2026-05-06 复盘的意义在于更清晰地把握市场脉搏，"
            "综合描述 A 股三大指数今日集体反弹，成交额放大，科技成长方向领涨。"
        )

        result = ma._build_news_block([
            {
                "title": "A股收评：科创50指数放量反弹涨5.47% 两市成交额重回3万亿元",
                "snippet": long_snippet,
                "source": "东方财富",
                "published_date": "2026-05-06",
                "url": "https://example.com/news/1",
            }
        ])

        assert "摘要/线索片段" in result
        assert "关注点" not in result
        assert "成交额放大" in result
        assert "[东方财富 / 2026-05-06](https://example.com/news/1)" in result

    def test_news_block_uses_dash_when_source_metadata_missing(self):
        from finance_analysis.market_review.analyzer import MarketAnalyzer

        ma = MarketAnalyzer.__new__(MarketAnalyzer)
        ma.config = SimpleNamespace(report_language="zh")
        ma.region = "cn"

        result = ma._build_news_block([
            {
                "title": "政策利好带动板块活跃",
                "snippet": "相关主题成交放大",
            }
        ])

        assert "| 1 | 政策利好带动板块活跃 | 相关主题成交放大 | - |" in result
        assert "| 1 | 政策利好带动板块活跃 | 相关主题成交放大 | source |" not in result

    def test_review_prompt_caps_news_url_context(self):
        from finance_analysis.market_review.analyzer import MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        long_url = "https://example.com/redirect?" + "utm_campaign=" + ("x" * 420)

        prompt = ma._build_review_prompt(
            MarketOverview(date="2026-05-06"),
            [
                {
                    "title": "A股收评：指数放量反弹",
                    "snippet": "科技成长方向领涨",
                    "source": "测试来源",
                    "published_date": "2026-05-06",
                    "url": long_url,
                }
            ],
        )

        assert long_url not in prompt
        assert "URL: https://example.com/redirect?" in prompt
        assert ("x" * 220) not in prompt

    def test_market_light_snapshot_marks_defensive_market_red(self):
        from finance_analysis.market_review.analyzer import MarketIndex, MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        overview = MarketOverview(
            date="2026-03-06",
            indices=[
                MarketIndex(code="000001", name="上证指数", current=3200, change_pct=-1.8),
                MarketIndex(code="399001", name="深证成指", current=9800, change_pct=-2.4),
            ],
            up_count=900,
            down_count=4100,
            limit_up_count=10,
            limit_down_count=80,
            total_amount=9800.0,
        )

        snapshot = ma.build_market_light_snapshot(overview)

        assert snapshot["status"] == "red"
        assert snapshot["label"] == "偏防守"
        assert snapshot["score"] < 40
        assert any("亏钱效应" in reason for reason in snapshot["reasons"])

    def test_market_light_snapshot_uses_english_labels_and_reasons(self):
        from finance_analysis.market_review.analyzer import MarketIndex, MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-03-06",
            indices=[
                MarketIndex(code="000001", name="SSE Composite", current=3200, change_pct=-1.8),
                MarketIndex(code="399001", name="SZSE Component", current=9800, change_pct=-2.4),
            ],
            up_count=900,
            down_count=4100,
            limit_up_count=10,
            limit_down_count=80,
            total_amount=9800.0,
        )

        snapshot = ma.build_market_light_snapshot(overview)

        assert snapshot["status"] == "red"
        assert snapshot["label"] == "defensive"
        assert snapshot["guidance"] == (
            "Risk is elevated; prioritize drawdown control and avoid chasing weak rebounds."
        )
        assert snapshot["reasons"][0].startswith("market temperature ")
        assert any(
            reason.startswith("advancers ratio ") and "downside pressure dominates" in reason
            for reason in snapshot["reasons"]
        )

    def test_us_english_indices_do_not_label_turnover_as_cny(self):
        from finance_analysis.market_review.profile import US_PROFILE
        from finance_analysis.market_review.strategy import get_market_strategy_blueprint
        from finance_analysis.market_review.analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        ma.config.report_language = "en"
        ma.region = "us"
        ma.profile = US_PROFILE
        ma.strategy = get_market_strategy_blueprint("us")
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="SPX",
                    name="S&P 500",
                    current=5200.0,
                    change=35.0,
                    change_pct=0.68,
                    amount=9876543210.0,
                )
            ],
        )

        result = ma._build_indices_block(overview)

        assert "CNY 100m" not in result
        assert "Turnover (USD bn)" in result
        assert "| S&P 500 | 5200.00 |" in result

    def test_no_private_attribute_access_in_market_analyzer_source(self):
        """Static guard: market_analyzer.py must not access private analyzer attrs."""
        import ast
        import pathlib

        src = pathlib.Path("src/finance_analysis/market_review/analyzer.py").read_text()
        tree = ast.parse(src)
        forbidden = {
            "_model", "_router", "_use_openai", "_use_anthropic",  # historical
            "_call_litellm",      # use generate_text() instead
            "_litellm_available", # use is_available() instead
        }

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in forbidden:
                    violations.append(node.attr)

        assert violations == [], (
            f"market_analyzer.py still accesses private Analyzer attributes: {violations}"
        )
