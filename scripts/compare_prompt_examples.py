"""Compare full prompts on explicitly synthetic fixtures; no model/provider calls.

Use PYTHONPATH=<baseline-worktree>/src to render an older implementation with
this same script. Token counts use o200k_base when tiktoken is installed.
"""

import argparse
import csv, io, json, re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from finance_analysis.options_intelligence.prompts import explanation_payload, render_input as option_input, EXPLANATION
from finance_analysis.holdings_review.prompt import render_input as holding_input, SYSTEM
from finance_analysis.earnings_outlook.prompts import render_input as earnings_input, OUTLOOK
from finance_analysis.signal_center.llm_context import conclusions, serialize
from finance_analysis.signal_center.decision import SCREEN_SYSTEM_PROMPT

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("label")
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
args.output_dir.mkdir(parents=True, exist_ok=True)


def render(fn, data, system):
    import inspect

    return system + "\n\n" + (fn(data, system) if len(inspect.signature(fn).parameters) > 1 else fn(data))


f = dict(
    text="预计经营利润改善，但成本压力仍可能影响指引。" * 4, kind="guidance", quarter="2026-Q3", source_ids=["s1", "s2"]
)
source = dict(source_id="s1", title="Company IR", url="https://example.com/ir", published_at="2026-11-04")
earnings = dict(
    context=dict(
        event=dict(symbol="TEST.US", reporting_period="2026-Q3"),
        data_cutoff="2026-11-05T00:00:00Z",
        guidance_evidence=[f],
        operating_evidence=[f],
        consensus={"eps": {"value": 1.2, "quarter": "2026-Q3"}},
    ),
    research=dict(
        sources=[source, dict(source, source_id="s2", url="https://example.com/filing")], facts=[f], conflicts=[]
    ),
)
events = [
    dict(
        contract_symbol="",
        event_type="IV_TERM_INVERSION",
        value=0.25,
        reference={"front": 0.65, "back": 0.4},
        severity=75,
        source="yfinance",
        feed_type="delayed",
        data_time="2026-11-04T21:00:00Z",
        explanation="短期限IV高于远期限",
    )
]
terms = [
    dict(expiration="2026-11-13", dte=9, atm_iv=0.65, source="yfinance", feed_type="delayed"),
    dict(expiration="2026-12-18", dte=44, atm_iv=0.4, source="yfinance", feed_type="delayed"),
]
contracts = [
    dict(
        symbol=f"TEST-C{i}",
        events=["VOLUME_OI_ANOMALY"],
        volume_percentile=90 + i / 10,
        volume_oi=2.4,
        data_source="yfinance",
        feed_type="delayed",
        oi_date="2026-11-03",
        quote_status="valid",
        limitations=["delayed quotes"],
    )
    for i in range(15)
]
events += [
    dict(
        contract_symbol=c["symbol"],
        event_type="VOLUME_OI_ANOMALY",
        value=2.4,
        reference={"threshold": 2},
        severity=72,
        source="yfinance",
        feed_type="delayed",
        data_time="2026-11-04T21:00:00Z",
        explanation="成交活跃，不代表净开仓",
    )
    for c in contracts
]
options = dict(
    symbol="TEST.US",
    trade_date="2026-11-04",
    computed_at="2026-11-04T21:00:00Z",
    events=events,
    term_structure=terms,
    contracts=contracts,
    limitations=["delayed quotes"],
    scores={},
)
days = [date(2026, 10, 1) + timedelta(days=i) for i in range(31)]
days = [day for day in days if day.weekday() < 5][:20]
bars = [[day.isoformat(), 100, 115, 90, 100 + i % 4, 1000 + i * 10] for i, day in enumerate(days)]
minutes = [
    [
        (datetime(2026, 11, 5, 19, 5, tzinfo=timezone.utc) + timedelta(minutes=5 * i)).isoformat(),
        100,
        115,
        90,
        100 + i % 4,
        1000 + i * 10,
    ]
    for i in range(12)
]
holdings = dict(
    market="US",
    as_of="2026-11-05T20:10:00Z",
    holdings=[
        dict(position_id=f"p{i}", symbol=f"TEST{i}.US", quantity=100, daily_bars=bars, minute_bars=minutes)
        for i in range(6)
    ],
    indices=[],
    portfolio={"cash": 5000, "valuation_complete": True},
)
v2 = dict(
    market="CN",
    signal_date="2026-11-04",
    source_availability={},
    market_regime=[],
    candidates=[
        dict(
            symbol=f"{i:06}.SH",
            name="合成样本",
            instrument_type="STOCK",
            nominated_by=["trend"],
            trends={"10": {"rank": i + 1, "alpha_score": 78.123456, "features": {"rs_10d": 0.0123456}}},
            industry=[],
        )
        for i in range(20)
    ],
)
view = conclusions(v2, [c["symbol"] for c in v2["candidates"]])
outputs = {
    "options": render(option_input, explanation_payload(options), EXPLANATION),
    "earnings": render(earnings_input, earnings, OUTLOOK),
    "holdings": SYSTEM + "\n\n" + holding_input(holdings),
    "signal_v2": render(serialize, view, SCREEN_SYSTEM_PROMPT),
}
try:
    import tiktoken

    encoder = tiktoken.get_encoding("o200k_base")
except (ImportError, ValueError):
    encoder = None
result = {}
for name, text in outputs.items():
    (args.output_dir / f"{args.label}-{name}.md").write_text(text)
    blocks = re.findall(r"^(`{3,})csv\n(.*?)^\1\s*$", text, re.M | re.S)
    result[name] = {
        "chars": len(text),
        "tokens_o200k_base": len(encoder.encode(text)) if encoder else None,
        "tables": len(blocks),
        "rows": sum(max(0, len(list(csv.reader(io.StringIO(body)))) - 1) for _, body in blocks),
    }
(args.output_dir / f"{args.label}-metrics.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))

evidence = {
    "options_has_term_inversion": "IV_TERM_INVERSION" in outputs["options"],
    "options_events": len(explanation_payload(options).get("events", [])),
    "options_contracts": len(explanation_payload(options)["anomalous_contracts"]),
    "earnings_fact_copies": outputs["earnings"].count(f["text"]),
    "holdings_has_recent_and_volume": all(
        k in outputs["holdings"] for k in ("recent_3_change_pct", "volume_last3_vs_prior3")
    ),
}
(args.output_dir / f"{args.label}-evidence.json").write_text(json.dumps(evidence, indent=2))
print(json.dumps(evidence, indent=2))
