"""Text-only LLM adapter for market review, independent of stock reports."""

import logging
from typing import Optional

from finance_analysis.llm import LLMClient, LLMRequest
from finance_analysis.market_review.runtime_config import get_market_review_runtime_config

logger = logging.getLogger(__name__)


class MarketReviewTextGenerator:
    SYSTEM_PROMPT = """你是一位专业的股票分析助手。

- 回答必须基于用户提供的数据与上下文
- 若信息不足，要明确指出不确定性
- 不要编造价格、财报或新闻事实
"""

    def __init__(self, *, config=None, uid: Optional[int] = None):
        self._config_override = config
        self.uid = uid

    def _get_runtime_config(self):
        return self._config_override or get_market_review_runtime_config()

    def is_available(self) -> bool:
        return self._get_runtime_config().llm.is_available()

    def generate_text(self, prompt: str) -> Optional[str]:
        try:
            return (
                LLMClient(self._get_runtime_config().llm)
                .complete_text(
                    LLMRequest(
                        prompt=prompt,
                        system_prompt=self.SYSTEM_PROMPT,
                        call_type="market_review",
                        uid=self.uid,
                    )
                )
                .text
            )
        except Exception as exc:
            logger.warning("Market review LLM failed: %s", exc)
            return None
