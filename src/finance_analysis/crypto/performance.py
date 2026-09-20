"""Derived mark-to-market performance from the contiguous, complete snapshot suffix."""

from datetime import timedelta
from decimal import MAX_EMAX, Decimal, localcontext

ZERO = Decimal(0)
ONE = Decimal(1)


def complete(row):
    before, after, delta = (row.get(key) for key in ("position_before", "position_after", "position_delta"))
    return (
        before is not None
        and after is not None
        and delta is not None
        and ZERO <= before <= ONE
        and ZERO <= after <= ONE
        and delta == after - before
        and row["price"] > 0
        and (after == 0 or (row.get("average_entry_price") or ZERO) > 0)
    )


def annualized_return(equity, days):
    if days <= 0:
        return None
    with localcontext() as context:
        context.Emax = MAX_EMAX
        return equity ** (Decimal(365) / days) - ONE


def performance(snapshots, state):
    rows = []
    for row in sorted(snapshots, key=lambda item: item["evaluated_at"]):
        if not complete(row):
            rows = []
            continue
        if rows and (
            row["evaluated_at"] != rows[-1]["evaluated_at"] + timedelta(minutes=15)
            or row["position_before"] != rows[-1]["position_after"]
        ):
            rows = []
        rows.append(row)
    equity = peak = ONE
    max_drawdown = ZERO
    curve, executions, trades = [], [], []
    cycle = None
    previous = None
    for row in rows:
        if previous:
            equity *= ONE + previous["position_after"] * (row["price"] / previous["price"] - ONE)
        peak = max(peak, equity)
        drawdown = equity / peak - ONE
        max_drawdown = min(max_drawdown, drawdown)
        curve.append(dict(evaluated_at=row["evaluated_at"], equity=equity, drawdown=drawdown))
        if row["position_delta"] != 0:
            executions.append(
                {
                    key: row[key]
                    for key in (
                        "evaluated_at",
                        "price",
                        "position_before",
                        "position_after",
                        "position_delta",
                        "action",
                        "reason",
                    )
                }
            )
        if row["position_before"] == 0 and row["position_after"] > 0:
            cycle = dict(
                entry_time=row["evaluated_at"], start_equity=equity, average_entry_price=row["average_entry_price"]
            )
        if cycle and row["position_after"] > 0:
            cycle["average_entry_price"] = row["average_entry_price"]
        if cycle and row["position_before"] > 0 and row["position_after"] == 0:
            trades.append(
                dict(
                    entry_time=cycle["entry_time"],
                    exit_time=row["evaluated_at"],
                    holding_seconds=int((row["evaluated_at"] - cycle["entry_time"]).total_seconds()),
                    average_entry_price=cycle["average_entry_price"],
                    exit_price=row["price"],
                    realized_return=equity / cycle["start_equity"] - ONE,
                )
            )
            cycle = None
        previous = row
    returns = [trade["realized_return"] for trade in trades]
    wins, losses = sum(value > 0 for value in returns), sum(value < 0 for value in returns)
    days = Decimal(str((rows[-1]["evaluated_at"] - rows[0]["evaluated_at"]).total_seconds())) / 86400 if rows else ZERO
    points = len(curve)
    if points > 1000:
        curve = [curve[index * (points - 1) // 999] for index in range(1000)]
    return dict(
        running_days=days,
        annualized_return=annualized_return(equity, days),
        equity_points_total=points,
        breakeven=len(trades) - wins - losses,
        performance_start_at=rows[0]["evaluated_at"] if rows else None,
        performance_end_at=rows[-1]["evaluated_at"] if rows else None,
        current_position=dict(position_pct=state.position_pct, average_entry_price=state.average_entry_price),
        execution_count=len(executions),
        closed_trades=len(trades),
        wins=wins,
        losses=losses,
        win_rate=Decimal(wins) / len(trades) if trades else None,
        average_trade_return=sum(returns, ZERO) / len(returns) if returns else None,
        total_return=equity - ONE,
        max_drawdown=max_drawdown,
        best_trade=max(returns) if returns else None,
        worst_trade=min(returns) if returns else None,
        recent_executions=list(reversed(executions[-50:])),
        recent_trades=list(reversed(trades[-50:])),
        equity_curve=curve,
    )
