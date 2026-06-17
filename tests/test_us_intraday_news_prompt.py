# -*- coding: utf-8 -*-
"""Tests for US intraday news integration in LLM prompts."""

from __future__ import annotations

from src.services.tasks.us_intraday_analysis.llm import build_intraday_batch_llm_prompt


def test_build_intraday_batch_llm_prompt_includes_news_context():
    prompt = build_intraday_batch_llm_prompt(
        candidates=[
            {
                "id": "NVDA|relative_strength_breakout",
                "symbol": "NVDA",
                "signal_type": "relative_strength_breakout",
                "metrics": {"change_15m": 1.2},
                "raw_context": {"bars_1m_tail": []},
                "recent_news": [
                    {
                        "id": "1",
                        "title": "NVDA launches new chip",
                        "description": "Product launch",
                        "url": "https://longbridge.com/news/1",
                    }
                ],
            }
        ],
        market_context={
            "QQQ": {"change_15m": 0.2},
            "market_news": [
                {
                    "id": "99",
                    "title": "Fed speech",
                    "description": "Macro headline",
                    "url": "https://longbridge.com/news/99",
                }
            ],
        },
    )

    assert "market_news" in prompt
    assert "recent_news" in prompt
    assert "NVDA launches new chip" in prompt
    assert "Fed speech" in prompt
    assert "新闻催化" in prompt
