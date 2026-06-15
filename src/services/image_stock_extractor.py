# -*- coding: utf-8 -*-
"""
===================================
图片股票代码提取 (Vision LLM)
===================================

从截图/图片中提取股票代码，使用 Vision LLM。
优先级：Gemini -> Anthropic -> OpenAI（首个可用）。
"""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import sys
import time
from typing import List, Optional, Tuple

from src.config import Config, get_config
from src.llm_client import build_completion_kwargs, validate_llm_config

logger = logging.getLogger(__name__)


class _LiteLLMPlaceholder:
    """Provide a patchable placeholder before litellm is imported."""

    completion = None


# Keep a patchable module attribute while still avoiding a hard import at module load.
litellm = sys.modules.get("litellm") or _LiteLLMPlaceholder()

EXTRACT_PROMPT = """请分析这张股票市场截图或图片，提取其中所有可见的股票代码及名称。

重要：若图中同时显示股票名称和代码（如自选股列表、ETF 列表），必须同时提取两者，每个元素必须包含 code 和 name 字段。

输出格式：仅返回有效的 JSON 数组，不要 markdown、不要解释。
每个元素为对象：{"code":"股票代码","name":"股票名称","confidence":"high|medium|low"}
- code: 必填，股票代码（A股6位、港股5位、美股1-5字母、ETF 如 159887/512880）
- name: 若图中有名称则必填（如 贵州茅台、银行ETF、证券ETF），与代码一一对应；仅当图中确实无名称时可省略
- confidence: 必填，识别置信度，high=确定、medium=较确定、low=不确定

示例（图中同时有名称和代码时）：
- 个股：600519 贵州茅台、300750 宁德时代
- 港股：00700 腾讯控股、09988 阿里巴巴
- 美股：AAPL 苹果、TSLA 特斯拉
- ETF：159887 银行ETF、512880 证券ETF、512000 券商ETF、512480 半导体ETF、515030 新能源车ETF

输出示例：[{"code":"600519","name":"贵州茅台","confidence":"high"},{"code":"159887","name":"银行ETF","confidence":"high"}]

禁止只返回代码数组如 ["159887","512880"]，必须使用对象格式。若未找到任何股票代码，返回：[]"""

# Valid confidence values; invalid ones normalized to medium
_VALID_CONFIDENCE = frozenset({"high", "medium", "low"})

# LLM sometimes returns JSON field names or markdown labels as "code"; filter these out
_FAKE_CODES = frozenset({"CODE", "NAME", "HIGH", "LOW", "MEDIUM", "CONFIDENCE", "JSON"})

ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
VISION_API_TIMEOUT = 60  # seconds; avoid long blocks on network/API issues

# Magic bytes for server-side MIME validation (client Content-Type can be forged)
_IMAGE_SIGNATURES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # bytes[8:12] must be WEBP, checked separately
}


def _verify_image_magic_bytes(image_bytes: bytes, mime_type: str) -> None:
    """Verify actual file content matches declared MIME type (rejects forged Content-Type)."""
    if len(image_bytes) < 12:
        raise ValueError("图片文件过小或损坏")
    if mime_type not in _IMAGE_SIGNATURES:
        raise ValueError(f"无法验证类型: {mime_type}")
    if mime_type == "image/webp":
        if image_bytes[:4] != b"RIFF" or image_bytes[8:12] != b"WEBP":
            raise ValueError("文件内容与声明的类型 image/webp 不匹配，可能被篡改")
        return
    for sig in _IMAGE_SIGNATURES[mime_type]:
        if image_bytes.startswith(sig):
            return
    raise ValueError(f"文件内容与声明的类型 {mime_type} 不匹配，可能被篡改")


def _normalize_code(raw: str) -> Optional[str]:
    """Normalize and validate a single stock code. A-shares & HK: 5-6 digits; US: 1-5 letters."""
    s = raw.strip().upper()
    if not s:
        return None
    # A-shares & HK: 5-6 digit codes (600519, 00700, 09988)
    if s.isdigit() and len(s) in (5, 6):
        return s
    # US stocks: 1-5 letters, optionally with . (e.g. BRK.B)
    if re.match(r"^[A-Z]{1,5}(\.[A-Z])?$", s):
        return s
    # 尝试去除 SH/SZ 后缀
    for suffix in (".SH", ".SZ", ".SS"):
        if s.endswith(suffix):
            base = s[: -len(suffix)].strip()
            if base.isdigit() and len(base) in (5, 6):
                return base
    return None


def _parse_codes_from_text(text: str) -> List[str]:
    """从 LLM 响应文本解析股票代码（legacy format）。"""
    seen: set[str] = set()
    result: List[str] = []

    # 优先尝试 JSON 数组；只移除开头的 markdown 围栏，避免 find("```") 误删结尾导致清空
    cleaned = text.strip()
    for start in ("```json", "```"):
        if cleaned.startswith(start):
            cleaned = cleaned[len(start) :].strip()
            break
    end_idx = cleaned.rfind("```")
    if end_idx >= 0:
        cleaned = cleaned[:end_idx].strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    c = _normalize_code(item)
                    if c and c not in seen and c not in _FAKE_CODES:
                        seen.add(c)
                        result.append(c)
            return result
    except json.JSONDecodeError:
        pass

    # 兜底：查找 5-6 位数字及美股代码
    for m in re.finditer(r"\b([0-9]{5,6}|[A-Z]{1,5}(\.[A-Z])?)\b", text, re.IGNORECASE):
        c = _normalize_code(m.group(1))
        if c and c not in seen and c not in _FAKE_CODES:
            seen.add(c)
            result.append(c)

    return result


def _parse_items_from_text(text: str) -> List[Tuple[str, Optional[str], str]]:
    """
    Parse LLM response into items (code, name, confidence).
    Tries new format first, fallback to legacy codes-only format.
    """
    cleaned = text.strip()
    for start in ("```json", "```"):
        if cleaned.startswith(start):
            cleaned = cleaned[len(start) :].strip()
            break
    end_idx = cleaned.rfind("```")
    if end_idx >= 0:
        cleaned = cleaned[:end_idx].strip()

    # Try new format: list of objects
    parsed_data = None
    try:
        parsed_data = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json

            parsed_data = repair_json(cleaned, return_objects=True)
            logger.debug("[ImageExtractor] json.loads failed, repaired malformed JSON response")
        except Exception:
            parsed_data = None

    if isinstance(parsed_data, list):
        seen: set[str] = set()
        result: List[Tuple[str, Optional[str], str]] = []
        for item in parsed_data:
            if not isinstance(item, dict):
                continue
            code_raw = item.get("code") if isinstance(item.get("code"), str) else None
            if not code_raw:
                continue
            code = _normalize_code(code_raw)
            if not code or code in seen or code in _FAKE_CODES:
                continue
            seen.add(code)
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                name = name.strip()
            else:
                name = None
            conf = item.get("confidence")
            if isinstance(conf, str) and conf.lower() in _VALID_CONFIDENCE:
                conf = conf.lower()
            else:
                conf = "medium"
            result.append((code, name, conf))
        if result:
            return result

    # Fallback: legacy format (codes only)
    codes = _parse_codes_from_text(text)
    if not codes:
        logger.info("[ImageExtractor] 无法解析为结构化 items，且 legacy code 提取为空")
    return [(c, None, "medium") for c in codes]


def _resolve_vision_model() -> str:
    """Determine the litellm model to use for vision."""
    cfg = get_config()
    return (cfg.vision_model or cfg.llm_model or "").strip()


def _call_litellm_vision(image_b64: str, mime_type: str) -> str:
    """Extract stock codes from an image using litellm."""
    global litellm
    cfg = get_config()
    model = _resolve_vision_model()
    if not model:
        raise ValueError("未配置 Vision 模型。请设置 VISION_MODEL 或 LLM_MODEL。")

    validate_llm_config(cfg, model=model)

    data_url = f"data:{mime_type};base64,{image_b64}"
    call_kwargs = build_completion_kwargs(
        cfg,
        model,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACT_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        max_tokens=1024,
        timeout=VISION_API_TIMEOUT,
    )

    if getattr(litellm, "completion", None) is None:
        import litellm as litellm_module
        litellm = litellm_module
    response = litellm.completion(**call_kwargs)
    if response and response.choices and response.choices[0].message.content:
        return response.choices[0].message.content
    raise ValueError("LiteLLM vision returned empty response")


def extract_stock_codes_from_image(
    image_bytes: bytes,
    mime_type: str,
) -> Tuple[List[Tuple[str, Optional[str], str]], str]:
    """
    从图片中提取股票代码及名称（使用 Vision LLM）。

    优先级：Gemini -> Anthropic -> OpenAI（首个可用）。
    支持多 Key 轮询与重试（最多 3 次，指数退避）。

    Args:
        image_bytes: 原始图片字节
        mime_type: MIME 类型（如 image/jpeg, image/png）

    Returns:
        (items, raw_text) - items 为 [(code, name?, confidence), ...]，raw_text 为原始 LLM 响应。

    Raises:
        ValueError: 图片无效、未配置 Vision API 或提取失败时。
    """
    mime_type = (mime_type or "image/jpeg").strip().lower().split(";")[0].strip()
    if mime_type not in ALLOWED_MIME:
        raise ValueError(f"不支持的图片类型: {mime_type}。允许: {list(ALLOWED_MIME)}")

    if not image_bytes:
        raise ValueError("图片内容为空")

    if len(image_bytes) > MAX_SIZE_BYTES:
        raise ValueError(f"Image too large (max {MAX_SIZE_BYTES // (1024 * 1024)}MB)")

    _verify_image_magic_bytes(image_bytes, mime_type)

    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            raw = _call_litellm_vision(image_b64, mime_type)
            logger.debug("[ImageExtractor] raw LLM response:\n%s", raw)
            items = _parse_items_from_text(raw)
            logger.info(
                f"[ImageExtractor] {_resolve_vision_model()} 提取 {len(items)} 个: "
                f"{[(i[0], i[1]) for i in items[:5]]}{'...' if len(items) > 5 else ''}"
            )
            return items, raw
        except Exception as e:
            last_error = e
            if attempt < 2:
                delay = 2 ** attempt
                logger.warning(f"[ImageExtractor] 尝试 {attempt + 1}/3 失败，{delay}s 后重试: {e}")
                time.sleep(delay)

    raise ValueError(
        f"Vision API 调用失败，请检查 API Key 与网络: {last_error}"
    ) from last_error
