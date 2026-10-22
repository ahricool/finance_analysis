from datetime import date, timedelta

from finance_analysis.stock_strategies.features import DailyInputs


def inputs(day=date(2026, 10, 19), prices=None, previous=None, month_end=False, market="US"):
    prices = prices or {"A.US": (100, 100), "B.US": (100, 100), "SPY.US": (100, 100)}
    previous = previous or {c: 100 for c in prices}
    features = {}
    instruments = {}
    for code, (opening, close) in prices.items():
        features[code] = dict(
            open=opening,
            close=close,
            high=close + 5,
            low=close - 5,
            volume=1e6,
            amount=1e8,
            valid=True,
            previous_close=previous[code],
            previous_high=previous[code] + 1,
            ma20=90,
            ma50=80,
            ma100=70,
            ma200=60,
            mom60=0.2,
            mom126=0.3,
            atr=5.0,
            liquidity=1e8,
            low20=50,
            regression=0.5,
            max_return=0.1,
            vol20=0.2,
            ema50=80,
            ema50_previous=79,
            force=-1,
        )
        instruments[code] = dict(name=code, type="ETF" if code == "SPY.US" else "STOCK")
    return DailyInputs(
        market=market,
        day=day,
        next_day=day + timedelta(days=1),
        month_end=month_end,
        features=features,
        instruments=instruments,
        stocks=("A.US", "B.US"),
        etfs=(),
        breadth_codes=("A.US", "B.US"),
        prices={
            c: {(day - timedelta(days=1)).isoformat(): previous[c], day.isoformat(): p[1]} for c, p in prices.items()
        },
        trends={40: {}, 60: {}},
        regimes={20: dict(regime="RISK_ON", score=80), 60: dict(regime="RISK_ON", score=80)},
        etf_regime="RISK_ON",
        benchmark="SPY.US",
    )
