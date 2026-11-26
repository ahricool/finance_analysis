"""Code-owned crypto strategy presets, shared by Demo and Live observation."""
INTERVAL_SECONDS = 5
SYMBOL = "ETHUSDT"
CATALOG = {
    "ema_cross": {"name": "EMA Cross", "description": "ETHUSDT · 闭合 5 分钟 EMA 9/21 交叉", "backtest": None},
    "perpetual_drive": {"name": "Perpetual Drive", "description": "ETHUSDT · UTC 驱动窗口与相对 BTC 强度", "backtest": None},
}


def config(key):
    return {
        "symbol": SYMBOL, "strategy_type": key, "name": CATALOG[key]["name"], "direction": "BOTH",
        "fast": 9, "slow": 21, "notional": "100", "margin": "100", "max_position": "100",
        "leverage_limit": 10, "max_loss": "10", "stop_pct": "2", "drive_range_pct": "0.8",
        "drive_move_pct": "1.2", "drive_efficiency": "0.48", "drive_relative_pct": "0.8",
    }
