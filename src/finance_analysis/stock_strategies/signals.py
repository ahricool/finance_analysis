"""Prior-close candidate order and exits; never inspect the execution session."""

from finance_analysis.stock_strategies.features import DataNotReady, finite


def decide(spec, state, data):
    candidates, exits = [], {}
    stock_codes = set(data.stocks)
    regime = (
        data.require_context(20 if spec.family == "hybrid" else 60) if spec.family in {"hybrid", "regression"} else None
    )
    if spec.family in {"trend_quality", "ma_market"}:
        regime = data.regimes.get(20)
        if not regime or not finite(regime.get("score")):
            raise DataNotReady(f"等待{data.day}正式Trend20市场分数")
    if spec.family == "trend_quality":
        if not data.trends.get(60) or 60 not in data.regimes:
            raise DataNotReady(f"等待{data.day}完整正式Trend60评分")
        for code in data.stocks:
            trend = data.trends[60].get(code)
            if data.stock_eligible(code) and (
                not trend
                or not all(finite(trend.get(k)) for k in ("trend_score", "rs_score", "path_score"))
                or not isinstance(trend.get("trend_candidate"), bool)
            ):
                raise DataNotReady(f"等待{code}正式Trend60路径质量与趋势条件")
    breadth, denominator = data.breadth50() if spec.breadth else (None, None)
    breadth_bad = state.get("breadth_bad", 0) + 1 if breadth is not None and breadth < 0.25 else 0
    macro_bad = (
        state.get("macro_bad", 0) + 1
        if regime and (regime["regime"] == "RISK_OFF" and data.etf_regime == "RISK_OFF")
        else 0
    )
    force_all = spec.breadth and breadth_bad >= 2
    market_off = regime and regime["regime"] == "RISK_OFF" and macro_bad >= 2
    benchmark_ok = True
    if spec.family == "hybrid":
        b = data.features.get(data.benchmark, {})
        if not finite(b.get("ma200")) or not b.get("valid"):
            raise DataNotReady("等待基准完整MA200日线")
        benchmark_ok = b["close"] > b["ma200"] and b["mom126"] > 0
        for period in (40, 60):
            if period not in data.trends:
                raise DataNotReady(f"等待{data.day}正式Trend{period}排名")
    stock_candidates, etf_candidates = [], []
    rank_pool = []
    for code in (*data.stocks, *data.etfs, *state.get("positions", {})):
        if code in exits:  # positions may already be in the frozen universe
            continue
        f = data.features.get(code, {})
        if not f.get("valid"):
            exits[code] = (
                ["20日市场分数触发清仓"]
                if spec.family in {"trend_quality", "ma_market"}
                and regime["score"] < (35 if spec.family == "trend_quality" else 40)
                else []
            )
            continue
        c = f["close"]
        is_etf = data.instruments.get(code, {}).get("type") == "ETF"
        eligible = finite(f.get("ma200")) and (is_etf or data.stock_eligible(code))
        if spec.risk_engine in {"20261021", "20261023"} and code == "CTVA.US":
            eligible = False
        reasons, entry, score = [], False, 0.0
        bull = finite(f.get("mom126")) and c > f.get("ma200", float("inf")) and f["mom126"] > 0
        if spec.family in {"ma", "ma_market"}:
            entry = eligible and data.stock_eligible(code) and bull and c > f["ma20"] > f["ma50"]
            score = f["ma20"] / f["ma50"] - 1 if finite(f.get("ma50")) else 0
            if c < f.get("ma20", 0):
                reasons.append("收盘跌破MA20")
            if spec.family == "ma_market" and regime["score"] < 40:
                reasons.append("20日市场分数低于40")
        elif spec.family == "trend_quality":
            trend = data.trends[60].get(code, {})
            entry = (
                code in stock_codes
                and not is_etf
                and eligible
                and trend.get("trend_candidate", False)
                and trend.get("trend_score", 0) >= 55
                and trend.get("rs_score", 0) >= 45
                and trend.get("path_score", 0) >= 65
            )
            score = trend.get("trend_score", 0)
            if c < f.get("ma20", 0):
                reasons.append("收盘跌破MA20")
            if regime["score"] < 35:
                reasons.append("20日市场分数低于35")
        elif spec.family == "momentum":
            entry = eligible and data.stock_eligible(code) and bull and f.get("mom60", 0) > 0
            score = f.get("mom60", 0)
            if c < f.get("ma50", 0):
                reasons.append("收盘跌破MA50")
        elif spec.family == "regression":
            entry = (
                not is_etf
                and eligible
                and c > f.get("ma100", float("inf"))
                and f.get("regression", 0) > 0
                and f.get("max_return", 1) < 0.20
            )
            score = f.get("regression", 0)
            if c < f.get("ma100", 0):
                reasons.append("收盘跌破MA100")
            if market_off:
                reasons.append("ETF与Trend60连续两日风险关闭")
        elif is_etf:
            trend = data.trends[40].get(code)
            if code in data.etfs and not trend:
                raise DataNotReady(f"等待ETF {code} 当日Trend40评分")
            entry = (
                eligible
                and bull
                and c > f["ema50"] > f["ema50_previous"]
                and f["force"] < 0
                and c < f["previous_close"]
                and benchmark_ok
                and bool(trend)
                and trend["trend_score"] >= 60
                and trend["rs_score"] >= 50
            )
            score = f["mom126"] / max(f["vol20"], 0.10) if finite(f.get("vol20")) else 0
            if f["force"] > 0 or c < f["ema50"]:
                reasons.append("ETF Force转正或跌破EMA50")
            if not benchmark_ok:
                reasons.append("基准长期趋势过滤关闭")
        else:
            trend = data.trends[60].get(code)
            entry = eligible and bool(trend) and trend["trend_score"] >= 60 and trend["rs_score"] >= 50
            score = trend["trend_score"] if trend else 0
            if c < f.get("low20", 0):
                reasons.append("收盘跌破此前20日低点")
            if regime["score"] < 60 or data.etf_regime != "RISK_ON":
                reasons.append("市场分数低于60或ETF非风险开启")
        if force_all:
            reasons.append("MA50广度连续两日低于25%")
        exits[code] = reasons
        if entry and not reasons and finite(score) and finite(f.get("atr")):
            item = dict(
                code=code,
                name=data.instruments.get(code, {}).get("name", code),
                score=float(score),
                atr=float(f["atr"]),
                type="ETF" if is_etf else "STOCK",
            )
            rank_pool.append(item)
            (etf_candidates if is_etf else stock_candidates).append(item)
    order = lambda x: (-x["score"], x["code"])
    rank_pool.sort(key=order)
    if data.month_end and spec.family in {"regression", "momentum"}:
        keep = {r["code"] for r in rank_pool[: 5 if spec.family == "regression" else 2]}
        for code in state.get("positions", {}):
            if code not in keep:
                exits.setdefault(code, []).append("月末排名退出")
    stock_candidates.sort(key=order)
    etf_candidates.sort(key=order)
    stock_candidates, etf_candidates = stock_candidates[:40], etf_candidates[:40]
    if spec.breakout:
        stock_candidates = [
            r for r in stock_candidates if data.features[r["code"]]["close"] > data.features[r["code"]]["previous_high"]
        ]
    stock_gate = spec.family != "hybrid" or (regime["regime"] == "RISK_ON" and data.etf_regime == "RISK_ON")
    if spec.family in {"trend_quality", "ma_market"}:
        stock_gate = regime["score"] >= (60 if spec.family == "trend_quality" else 65)
    if spec.family == "regression":
        stock_gate = data.etf_regime != "RISK_OFF" and not market_off
    if spec.family == "momentum" and not data.month_end:
        stock_gate = False
    if stock_gate:
        candidates.extend(stock_candidates)
    candidates.extend(etf_candidates)
    if spec.family != "hybrid":
        candidates = rank_pool[:40] if stock_gate else []
    if spec.breadth and (breadth < 0.40 or force_all):
        candidates = []
    candidates = [r for r in candidates if not exits.get(r["code"])]
    return dict(
        candidates=candidates,
        exits=exits,
        breadth_bad=breadth_bad,
        macro_bad=macro_bad,
        breadth=breadth,
        breadth_denominator=denominator,
    )
