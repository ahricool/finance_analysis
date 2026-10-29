"""V2 redistribution, alternative trend routes, shortlist and deterministic selection."""

from copy import deepcopy
from datetime import date
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, text

from finance_analysis.confluence import v2
from finance_analysis.confluence.service import ConfluenceService

DAY = date(2026, 10, 28)


def inputs():
    return dict(
        macro=dict(adaptation_score=80, risk_score=80, regime="RISK_ON"),
        etf=dict(etfs=[dict(composite_score=80)]),
        industry=dict(strength_score=80, industry_name="行业"),
        trend=dict(trend_score=80, state="TRENDING", features={}),
        quant=dict(final_score=0.8, signal="buy"),
        options=dict(scores={"bearish_demand": {"value": 20}, "liquidity_risk": {"value": 20}}),
        sentiment=dict(heat_score=80, state="ACTIVE"),
        dragon_tiger=dict(net_inflow=100),
    )


def score(facts):
    return v2.aggregate({key: v2.evaluate(key, facts.get(key)) for key in v2.WEIGHTS})


def test_weights_primary_secondary_and_exact_missing_redistribution():
    assert sum(v2.WEIGHTS[k] for k in v2.PRIMARY) == 80
    assert sum(v2.WEIGHTS.values()) == 100
    facts = inputs()
    facts["industry"] = facts["options"] = facts["sentiment"] = facts["dragon_tiger"] = None
    result = score(facts)
    assert result["confluence_score"] == 80
    assert result["available_weight"] == 72
    for key in ["industry", "options", "sentiment", "dragon_tiger"]:
        assert result["signals"][key]["strength"] is None
        assert result["signals"][key]["normalized_weight"] is None
        assert result["signals"][key]["contribution"] is None
    assert sum(s["normalized_weight"] or 0 for s in result["signals"].values()) == pytest.approx(100, abs=1e-5)
    assert sum(s["contribution"] or 0 for s in result["signals"].values()) == pytest.approx(80, abs=1e-5)
    assert result["eligible"] and result["strong_confluence"]


def test_missing_core_values_are_not_neutral_and_zero_is_real_evidence():
    assert v2.evaluate("industry", dict(strength_rank=1))["strength"] is None
    assert v2.evaluate("etf", dict(etfs=[dict(rank=1)]))["strength"] is None
    assert v2.evaluate("quant", dict(final_score=90))["strength"] is None
    assert v2.evaluate("macro", dict(adaptation_score=float("nan")))["strength"] is None
    assert v2.evaluate("macro", dict(adaptation_score=0))["strength"] == 0
    assert v2.evaluate("dragon_tiger", dict(net_inflow=0))["strength"] == 50
    assert not score(dict(macro=dict(adaptation_score=100), sentiment=dict(heat_score=100)))["eligible"]
    assert not score(dict(trend=dict(trend_score=100, state="TRENDING")))["eligible"]
    contexts = inputs()
    assert not score({key: contexts[key] for key in ("macro", "industry", "etf")})["eligible"]


def test_three_period_alternative_routes_and_inactive_versus_absent():
    facts = dict(
        periods=[
            dict(
                trend_period=20,
                state="BROKEN",
                trend_score=90,
                features=dict(box_state="NONE", mr_state="MR_REBOUND", mr_quality=80),
            ),
            dict(trend_period=40, state="TRENDING", alpha_score=70, features={}),
            dict(
                trend_period=60,
                state="TRENDING",
                alpha_score=80,
                features=dict(box_state="BOX_BREAKOUT", box_quality=90, mr_state="MR_NONE"),
            ),
        ]
    )
    value = v2.evaluate("trend", facts)
    assert value["strength"] == 80  # mean(80, 70, 90), never sum nine correlated cells.
    matrix = value["evidence"]["matrix"]
    assert matrix[0]["routes"] == dict(trend=20, breakout=0, rebound=80)
    assert matrix[1]["routes"]["breakout"] is None
    assert matrix[2]["dominant"] == "breakout"
    mature = v2.evaluate("trend", dict(state="TRENDING", trend_lifecycle="MATURE", alpha_score=85))
    assert mature["status"] == "positive"


def test_options_activity_is_not_bullish_and_risks_are_inverted():
    assert v2.evaluate("options", dict(scores={"unusual_activity": {"value": 100}}))["strength"] is None
    value = v2.evaluate("options", dict(scores={"bearish_demand": {"value": 90}, "liquidity_risk": {"value": 70}}))
    assert value["strength"] == 20 and value["status"] == "negative"
    assert v2.evaluate("sentiment", dict(heat_score=99, state="DIVERGENCE"))["strength"] == 45


class MemoryRepository:
    def __init__(self, count=25):
        self.stocks = [dict(id=i, code=f"{i:06d}.SH", name=str(i)) for i in range(1, count + 1)]
        self.saved = {}

    def instruments(self, market):
        return self.stocks

    def trend_v2(self, market, day):
        return [
            dict(instrument_id=s["id"], trend_period=20, trade_date=day, state="TRENDING", alpha_score=90)
            for s in reversed(self.stocks)
        ]

    def classification(self, market, day):
        industry = (
            dict(industry_code="881271.TI")
            if market == "CN"
            else dict(industry_code="Software—Application", sector="Technology")
        )
        return [dict(code=s["code"], trade_date=day, industries=[industry]) for s in self.stocks]

    def macro(self, market, day):
        return [dict(trade_date=day, risk_score=90, states=dict(credit="HEALTHY", rates="EASING"))]

    def etf(self, market, day, **kwargs):
        return [dict(code=s["code"], trade_date=day, etfs=[dict(composite_score=85)]) for s in self.stocks]

    def industry(self, *args):
        return []

    quant = options = sentiment = dragon_tiger = industry

    def read(self, market, day):
        return dict(items=self.saved.get((market, day), {}).get("rows", []))

    def save(self, market, day, rows, manifest):
        self.saved[market, day] = dict(rows=deepcopy(rows), manifest=deepcopy(manifest))
        return True


def test_shortlist_is_deterministic_per_market_and_rerun_never_accumulates():
    repo = MemoryRepository()
    service = ConfluenceService(repo)
    assert service.run("CN", DAY)["candidate_count"] == 25
    rows = repo.saved["CN", DAY]["rows"]
    assert [r["instrument_id"] for r in rows if r["eligible"]] == list(range(1, 11))
    assert len(rows) == 25
    assert service.run("CN", DAY)["count"] == 10
    assert len(repo.saved["CN", DAY]["rows"]) == 25
    assert service.run("US", DAY)["count"] == 10
    repo.stocks = repo.stocks[:3]
    assert service.run("CN", DAY)["count"] == 3
    assert len(repo.saved["US", DAY]["rows"]) == 25


def test_future_or_failed_sources_stay_missing_and_no_padding():
    repo = MemoryRepository(3)
    repo.etf = lambda *args, **kwargs: [
        dict(code="000001.SH", trade_date=date(2099, 1, 1), etfs=[dict(composite_score=100)])
    ]
    assert ConfluenceService(repo).run("CN", DAY)["count"] == 3  # macro + trend still qualify.
    assert repo.saved["CN", DAY]["rows"][0]["signals"]["etf"]["status"] == "unavailable"
    repo.macro = lambda *args: (_ for _ in ()).throw(RuntimeError("offline"))
    assert ConfluenceService(repo).run("CN", DAY)["count"] == 0
    assert repo.saved["CN", DAY]["manifest"]["source_availability"]["macro"]["status"] == "failed"


def test_v2_migration_preserves_v1_and_rejects_destructive_downgrade():
    spec = importlib.util.spec_from_file_location(
        "v2migration", Path(__file__).parents[2] / "alembic/versions/0079_confluence_v2.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(
            text(
                "CREATE TABLE confluence_snapshot (id INTEGER PRIMARY KEY, available_signal_count INTEGER NOT NULL, "
                "positive_signal_count INTEGER NOT NULL, CONSTRAINT ck_confluence_counts CHECK "
                "(positive_signal_count <= available_signal_count AND available_signal_count BETWEEN 0 AND 5))"
            )
        )
        c.execute(text("INSERT INTO confluence_snapshot VALUES (1, 4, 3)"))
        migration.op = Operations(MigrationContext.configure(c))
        migration.upgrade()
        assert c.execute(text("SELECT * FROM confluence_snapshot WHERE id=1")).one() == (1, 4, 3)
        c.execute(text("INSERT INTO confluence_snapshot VALUES (2, 8, 7)"))
        with pytest.raises(RuntimeError, match="cannot safely downgrade"):
            migration.downgrade()
        c.execute(text("DELETE FROM confluence_snapshot WHERE id=2"))
        migration.downgrade()
        assert c.execute(text("SELECT * FROM confluence_snapshot")).one() == (1, 4, 3)


def test_multi_industry_averages_all_core_values_and_labels_them_together():
    result = v2.evaluate(
        "industry",
        {
            "industries": [
                dict(industry_name="一级", strength_score=90, state="STRONG"),
                dict(industry_name="细分", strength_score=50, state="NEUTRAL"),
            ]
        },
    )
    assert result["strength"] == result["evidence"]["strength_score"] == 70
    assert result["evidence"]["industry_name"] == "一级 / 细分"
    assert result["evidence"]["state"] == "行业状态分化"


@pytest.mark.parametrize("quant, expected, eligible", [(0.242, 59.99, False), (0.242857143, 60, True)])
def test_sixty_boundary_keeps_primary_positive_and_stock_evidence_requirements(quant, expected, eligible):
    result = score(
        dict(
            etf=dict(etfs=[dict(composite_score=65)]),
            trend=dict(alpha_score=65, state="TRENDING"),
            quant=dict(final_score=quant),
        )
    )
    assert result["confluence_score"] == expected and result["eligible"] is eligible
    assert not result["strong_confluence"]
    assert v2.rules()["minimum_score"] == 60 and v2.rules()["strong_min_score"] == 75


@pytest.mark.parametrize("market", ["CN", "US"])
def test_research_top_fifty_is_separate_from_daily_ten_formal_signals(market):
    repo = MemoryRepository(75)
    result = ConfluenceService(repo).run(market, DAY)
    stored = repo.saved[market, DAY]
    assert result["count"] == 10 and result["ranked_count"] == 50 and result["candidate_count"] == 75
    assert len(stored["rows"]) == 50
    assert sum(row["eligible"] for row in stored["rows"]) == 10
    assert sum(row["strong_confluence"] for row in stored["rows"]) == 10
    assert all(not row["eligible"] and not row["strong_confluence"] for row in stored["rows"][10:])
    assert stored["manifest"]["rules"]["minimum_score"] == 60
    assert stored["manifest"]["source_availability"]["selection"]["selected_count"] == 10
    ConfluenceService(repo).run(market, DAY)
    assert len(repo.saved[market, DAY]["rows"]) == 50


@pytest.mark.parametrize("market", ["CN", "US"])
def test_below_sixty_observations_are_saved_without_becoming_formal_signals(market):
    repo = MemoryRepository(12)
    repo.macro = lambda *_: []
    repo.etf = lambda *_, **_kw: [
        dict(code=s["code"], trade_date=DAY, etfs=[dict(composite_score=65)]) for s in repo.stocks
    ]
    repo.trend_v2 = lambda *_: [
        dict(instrument_id=s["id"], trade_date=DAY, trend_period=20, state="TRENDING", alpha_score=65)
        for s in repo.stocks
    ]
    repo.quant = lambda *_: [
        dict(instrument_id=s["id"], trade_date=DAY, final_score=0.242857143 if s["id"] <= 2 else 0.1)
        for s in repo.stocks
    ]
    result = ConfluenceService(repo).run(market, DAY)
    rows = repo.saved[market, DAY]["rows"]
    assert result["count"] == 2 and result["ranked_count"] == 12
    assert [row["instrument_id"] for row in rows[:2]] == [1, 2]
    assert all(
        row["confluence_score"] == 58.25 and not row["eligible"] and not row["strong_confluence"] for row in rows[2:]
    )
    assert all("低于60分" in " ".join(row["reasons"]) for row in rows[2:])


def test_selected_signals_remain_visible_when_outside_observation_score_top_fifty():
    repo=MemoryRepository(60)
    repo.classification=lambda *_:[dict(code=s["code"],trade_date=DAY,
        industries=[dict(industry_code="881271.TI")]) for s in repo.stocks if s["id"]>10]
    repo.macro=lambda *_:[dict(trade_date=DAY,risk_score=67.5)]  # CN growth adaptation 64, neutral.
    repo.etf=lambda *_,**_kw:[dict(code=s["code"],trade_date=DAY,
        etfs=[dict(composite_score=65 if s["id"]<=10 else 100)]) for s in repo.stocks]
    repo.trend_v2=lambda *_:[dict(instrument_id=s["id"],trade_date=DAY,trend_period=20,state="TRENDING",
        alpha_score=65 if s["id"]<=10 else 100) for s in repo.stocks]
    repo.quant=lambda *_:[dict(instrument_id=s["id"],trade_date=DAY,final_score=.242857143)
        for s in repo.stocks if s["id"]<=10]
    result=ConfluenceService(repo).run("CN",DAY)
    rows=repo.saved["CN",DAY]["rows"]
    assert result["candidate_count"]==60 and result["count"]==10 and len(rows)==50
    assert [r["instrument_id"] for r in rows if r["eligible"]]==list(range(1,11))
    assert all(r["confluence_score"]==60 for r in rows[:10])
    assert all(r["confluence_score"]>90 and not r["strong_confluence"] for r in rows[10:])
