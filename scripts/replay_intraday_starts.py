"""Compare quote-time rules on archived FA inputs; never substitute OHLC for quotes.

Input JSON: bars maps symbol to original CandleState versions. Optional ticks maps
symbol to the complete sequence of scheduler {at, quote} snapshots (quote may be
null). Optional trades is a list of completed, frozen production trade payloads.
Output is per symbol/day/scenario. Without archived ticks only shape counts exist.
"""
import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean

from finance_analysis.integrations.market_data.realtime_state.models import CandleState, QuoteState
from finance_analysis.intraday_options.config import SYMBOLS
from finance_analysis.intraday_options.opportunities import calculate_opportunities, start_branches
from finance_analysis.intraday_options.rules import StartPolicy
from finance_analysis.intraday_options.scoring import closed_session_bars
from finance_analysis.intraday_options.simulation import target_space, transition
from finance_analysis.intraday_options.structure import execution_context
from finance_analysis.market_stream.config import market_trading_date
from finance_analysis.market_stream.session import session_bounds

MINUTE = timedelta(minutes=1)


def scenarios():
    for opening in (0, 5, 15):
        for fraction, rr in ((0, 0), (0, .5), (0, 1), (.0005, 0), (.001, 0), (.0015, 0), (.001, .5), (.001, 1)):
            yield (opening, fraction, rr), StartPolicy(
                opening_enabled=bool(opening),
                pivot_enabled=bool(opening),
                midday_wave_enabled=False,
                box_enabled=True,
                continuation_enabled=True,
                recovery_enabled=True,
                use_pivot_target=True,
                opening_minutes=opening or 5,
                opening_min_range_pct=0.0,
                minimum_return=fraction,
                minimum_rr=rr,
                minimum_risk_return=0.0,
                maximum_risk_return=0.0,
                require_vwap=False,
                require_spy_alignment=False,
                min_open_move=0.0,
                pool_leader_top_k=0,
            )


def quote_at(symbol, raw):
    if raw is None:
        return None
    return QuoteState(symbol, trading_date=date.fromisoformat(raw["trading_date"]),
                      last_price=Decimal(str(raw["last_price"])), event_time=datetime.fromisoformat(raw["event_time"]),
                      received_at=datetime.fromisoformat(raw["received_at"]), timestamp_kind=raw.get("timestamp_kind", "provider"))


def outcomes(trades, cost_bps):
    rows = [t for t in trades if not t.get("estimated")]
    net = [((t["exit_price"]-t["entry_price"])*t["side"] - cost_bps/10000*t["entry_price"])
           / abs(t["entry_price"]-t["invalidation"]) for t in rows]
    short = sum(t["duration_seconds"] < 60 and t["exit_reason"] == "到达目标" for t in rows)
    return dict(closed=len(rows), fast_targets=short, fast_share=short/len(rows) if rows else None,
                mean_net_r=mean(net) if net else None, positive_net=sum(v > 0 for v in net))


def frozen_comparison(trades, settings, cost):
    keep, blocked = [], []
    for t in trades:
        e = t["entry_evidence"]
        metrics = target_space(t["entry_price"], e["invalidation"], e["target"], t["side"], False, settings)
        (blocked if metrics["space_rejections"] else keep).append(t)
    return dict(retained=outcomes(keep, cost), blocked=outcomes(blocked, cost))


def compare(symbol, day, bars, ticks, cost):
    opening, close = session_bounds("US", day)
    cutoff = close - timedelta(hours=2)
    cases = dict(scenarios())
    states, confirmations, rejected, fills = {}, defaultdict(set), defaultdict(set), defaultdict(list)
    entered = defaultdict(int)
    previous = None
    # A minute-only diagnostic observes at close+5s. It makes no execution decisions.
    observations = ([(datetime.fromisoformat(t["at"]), quote_at(symbol, t["quote"])) for t in ticks]
                    if ticks else [(opening + i*MINUTE + timedelta(seconds=5), None)
                                   for i in range(1, int((cutoff-opening)/MINUTE))])
    for now, quote in sorted(observations, key=lambda item: item[0]):
        closed = closed_session_bars(symbol, bars, now)
        signature = tuple(id(b) for b in closed)
        if signature != previous:
            previous = signature
            results = {}
            if closed:
                end = closed[-1].bar_time + MINUTE
                base = calculate_opportunities(
                    closed,
                    StartPolicy(
                        opening_enabled=False,
                        pivot_enabled=False,
                        midday_wave_enabled=False,
                        box_enabled=True,
                        continuation_enabled=True,
                        recovery_enabled=True,
                    ),
                )
                common = dict(as_of=end.isoformat(), trading_date=day.isoformat(), **execution_context(closed))
                for n in (0, 5, 15):
                    branches = list(base["branches"])
                    levels = {}
                    if n:
                        start_cfg = StartPolicy(
                            opening_minutes=n,
                            opening_min_range_pct=0.0,
                            pivot_enabled=True,
                            midday_wave_enabled=False,
                        )
                        branches.extend(start_branches(closed, opening, start_cfg, levels))
                    results[n] = dict(**common, opportunities={**base, "branches": branches, "start_levels": levels})
                    if now < cutoff and now-end <= timedelta(seconds=75):
                        confirmations[n].update(b["structure_id"] for b in branches if b["status"] == "confirmed"
                                                and not b.get("superseded_by") and not b.get("breakout_rejection")
                                                and (not base["reference"] or b["kind"] == "opening_breakout"))
        if ticks:
            for key, settings in cases.items():
                state, events = transition(states.get(key), symbol, results.get(key[0]), quote, now, settings)
                states[key] = state
                rejected[key].update(p["process_id"] for p in state["plans"] if p.get("space_rejections")
                                     and p["execution_reason"] == "、".join(p["space_rejections"]))
                entered[key] += sum(e["kind"] == "entry" for e in events)
                fills[key].extend(e["trade"] for e in events if e["kind"] == "exit")
    return [dict(symbol=symbol, date=str(day), opening=n, minimum_return=f, minimum_rr=r,
                 candidates=len(confirmations[n]), new_candidates=len(confirmations[n]-confirmations[0]),
                 fills=entered[key] if ticks else None,
                 blocked_processes=len(rejected[key]) if ticks else None,
                 outcomes=outcomes(fills[key], cost) if ticks else None)
            for key in cases for n, f, r in [key]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--cost-bps", type=float, default=2., help="Round-trip cost on entry underlying notional")
    args = parser.parse_args()
    archive = json.loads(args.archive.read_text())
    results = []
    for symbol, records in archive["bars"].items():
        if symbol not in SYMBOLS:
            continue
        days = defaultdict(list)
        for record in records:
            if not record.get("received_at"):
                raise ValueError("Replay requires original receipt timestamps")
            b = CandleState.from_mapping(record)
            days[market_trading_date(b.bar_time, "US")].append(b)
        for day, bars in days.items():
            ticks = [t for t in archive.get("ticks", {}).get(symbol, [])
                     if market_trading_date(datetime.fromisoformat(t["at"]), "US") == day]
            results.extend(compare(symbol, day, bars, ticks, args.cost_bps))
    cohorts = defaultdict(list)
    for trade in archive.get("trades", []):
        if trade["symbol"] in SYMBOLS:
            cohorts[trade["trading_date"]].append(trade)
    sensitivity = [dict(date=day, minimum_return=f, minimum_rr=r, **frozen_comparison(trades, settings, args.cost_bps))
                   for day, trades in cohorts.items() for (n, f, r), settings in scenarios() if n == 0]
    print(json.dumps(dict(cost_bps=args.cost_bps, scenarios=results, frozen_trades=sensitivity), allow_nan=False))


if __name__ == "__main__":
    main()
