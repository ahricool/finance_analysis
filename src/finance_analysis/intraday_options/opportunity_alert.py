"""Global, once-per-confirmed-structure alerts for both rolling market feeds."""
import asyncio
from datetime import datetime, timedelta
import logging

from finance_analysis.intraday_options.notification import KIND_LABELS
from finance_analysis.notification.service import get_notification_service

logger = logging.getLogger(__name__)


async def alert_opportunity(redis, symbol, primary, as_of, quote_at, now):
    if not primary or not quote_at:
        return
    if not (timedelta(0) <= now - quote_at <= timedelta(seconds=60)
            and timedelta(0) <= now - as_of < timedelta(seconds=90)
            and now < datetime.fromisoformat(primary["expires_at"])):
        return
    key = f"rt:rolling-alert:{symbol}:{primary['structure_id']}"
    try:
        if not await redis.set(key, "claimed", ex=86400, nx=True):
            return
        kind = KIND_LABELS[primary["kind"]]
        direction = "偏多" if primary["direction"] == "bullish" else "偏空"
        title = f"{symbol} 短线机会 · {kind} · {direction}"
        confirmed = datetime.fromisoformat(primary["confirmed_at"])
        expires = datetime.fromisoformat(primary["expires_at"])
        content = (f"{title}\n形态质量 {primary['quality_score']:.0f} 分，触发位 {primary['trigger']:.8g}，"
                   f"失效位 {primary['invalidation']:.8g}。\n确认于 {confirmed:%Y-%m-%d %H:%M %Z}，"
                   f"有效至 {expires:%H:%M %Z}。")

        def deliver():
            return get_notification_service().send(content, title=title, route_type="alert", severity="info",
                                                   dedup_key=key, cooldown_key=key)

        try:
            persisted = await asyncio.to_thread(deliver)
            if persisted.notification_id is None:
                await redis.delete(key)
        except Exception:
            await redis.delete(key)
            raise
    except Exception:
        logger.exception("短线机会提醒失败: %s", symbol)
