"""Serialize switches with the existing account control and freeze equity boundaries."""
from datetime import timezone
from decimal import Decimal

from sqlalchemy import select

from finance_analysis.core.time import utc_now
from finance_analysis.crypto_strategy.catalog import CATALOG, INTERVAL_SECONDS, SYMBOL, config
from finance_analysis.database.models.crypto_strategy import CryptoStrategyPeriod as Period
from finance_analysis.database.models.live_trade import LiveAccountSnapshot
from finance_analysis.database.models.paper_trade import PaperAccountSnapshot, PaperIntent, PaperStrategy
from finance_analysis.database.repositories import live_trade, paper_trade


def active(session, environment):
    return session.scalar(select(Period).where(Period.environment == environment, Period.ended_at.is_(None)))


def activate_paper(session, strategy, view, now):
    rows = list(session.scalars(select(PaperStrategy).with_for_update()))
    if any(p["symbol"] == SYMBOL and Decimal(str(p["positionAmt"])) for p in view.get("positions", [])):
        raise ValueError("已有策略标的仍有持仓，请在平仓后切换")
    pending = select(PaperIntent.id).where(PaperIntent.symbol == SYMBOL, PaperIntent.status.in_(
        ["QUEUED", "SUBMITTING", "UNKNOWN", "SUBMITTED", "PARTIALLY_FILLED"])).limit(1)
    if session.scalar(pending):
        raise ValueError("仍有待核对的委托，请稍后切换")
    if SYMBOL not in view.get("demo_symbols", []) or SYMBOL not in view.get("shared_symbols", []):
        raise ValueError("策略标的尚无共享行情或 Demo 交易资格")
    if view.get("configuration", {}).get("dualSidePosition") is not False:
        raise ValueError("策略要求单向持仓模式")
    if strategy == "perpetual_drive" and (
        SYMBOL not in view.get("demo_coin_symbols", []) or "BTCUSDT" not in view.get("shared_symbols", [])
    ):
        raise ValueError("驱动策略需要加密合约和 BTC 基准行情")
    for row in rows:
        row.enabled, row.status, row.updated_at = False, "PAUSED", now
    selected = next((r for r in rows if r.symbol == SYMBOL), None)
    if selected is None:
        selected = PaperStrategy(symbol=SYMBOL)
        session.add(selected)
    selected.config, selected.enabled, selected.updated_at = config(strategy), True, now
    selected.status, selected.cursor = "WAITING", int(now.timestamp()) // 300 * 300_000


def switch(environment, strategy, actor):
    if strategy not in CATALOG or environment not in ("paper", "live"):
        raise ValueError("未知策略或交易环境")
    with paper_trade.session_scope() as session:
        lock = paper_trade.locked_trade_control if environment == "paper" else live_trade.locked_control
        lock(session)
        previous = active(session, environment)
        if previous and previous.strategy == strategy:
            return
        model = PaperAccountSnapshot if environment == "paper" else LiveAccountSnapshot
        snapshot = session.scalar(select(model).order_by(model.id.desc()).limit(1))
        now = utc_now()
        if not snapshot or not snapshot.payload.get("complete") or not (
            0 <= (now - snapshot.observed_at.replace(tzinfo=timezone.utc)).total_seconds() <= 90
        ):
            raise ValueError("请等待最新完整账户快照后再切换")
        amount = snapshot.payload.get("account", {}).get("totalMarginBalance")
        if amount is None or not Decimal(str(amount)).is_finite():
            raise ValueError("账户权益不可用")
        equity = Decimal(str(amount))
        if environment == "paper":
            activate_paper(session, strategy, snapshot.payload, now)
        if previous:
            previous.end_equity, previous.ended_at = equity, now
            session.flush()
        session.add(Period(environment=environment, strategy=strategy, actor_id=actor, started_at=now, start_equity=equity))


def overview():
    with paper_trade.session_scope() as session:
        items = {k: dict(v, key=k, parameters=config(k), periods=[], paper=None, live=None) for k, v in CATALOG.items()}
        selected = {"paper": None, "live": None}
        for r in session.scalars(select(Period).order_by(Period.id.desc())):
            item = items[r.strategy]
            pnl = None if r.end_equity is None else r.end_equity - r.start_equity
            item["periods"].append(dict(environment=r.environment, start=r.started_at, end=r.ended_at, profit=pnl,
                                        start_equity=r.start_equity, end_equity=r.end_equity))
            if pnl is None:
                selected[r.environment] = r.strategy
            else:
                item[r.environment] = (item[r.environment] or Decimal(0)) + pnl
        return {"items": list(items.values()), "selected": selected, "interval_seconds": INTERVAL_SECONDS}
