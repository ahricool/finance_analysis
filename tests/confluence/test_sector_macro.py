"""Industry sensitivities, missingness, signed contributions and cross-market boundaries."""

from copy import deepcopy

import pytest

from finance_analysis.confluence import v2
from finance_analysis.confluence.sector_macro import adapt, profile_for, PROFILES


def classification(code, sector=None):
    return dict(industries=[dict(industry_code=code, industry_name=code, sector=sector)])


def background(risk=20, credit="WEAK", rates="PRESSURE"):
    return dict(risk_score=risk, regime="RISK_OFF", states=dict(credit=credit, rates=rates), trade_date="2026-10-28")


def test_same_background_supports_defensive_and_penalizes_growth_without_reversing_banks():
    macro = background()
    growth = adapt(macro, classification("Software—Application", "Technology"), "US")
    defense = adapt(macro, classification("Packaged Foods", "Consumer Defensive"), "US")
    bank = adapt(macro, classification("Banks—Regional", "Financial Services"), "US")
    assert growth["adaptation_score"] == 10
    assert defense["adaptation_score"] == 53  # limited defense, rates pressure remains negative
    assert bank["adaptation_score"] == 14  # weak credit must not mechanically benefit banks
    assert growth["risk_score"] == defense["risk_score"] == bank["risk_score"] == 20
    strong = background(80, "HEALTHY", "EASING")
    assert adapt(strong, classification("Software—Application", "Technology"), "US")["adaptation_score"] == 90
    assert adapt(strong, classification("Packaged Foods", "Consumer Defensive"), "US")["adaptation_score"] == 47


def test_cn_uses_global_style_only_and_never_treats_us_rates_as_domestic_policy():
    growth = classification("881271.TI")
    first = adapt(background(20), growth, "CN")
    second = adapt(background(20, "HEALTHY", "EASING"), growth, "CN")
    assert first["adaptation_score"] == second["adaptation_score"] == 26
    defensive = adapt(background(20), classification("881134.TI"), "CN")
    assert defensive["adaptation_score"] == 62
    assert all(t["key"] == "risk" for p in defensive["profiles"] for t in p["terms"])
    assert adapt(background(0), classification("881134.TI"), "CN")["adaptation_score"] == 70


@pytest.mark.parametrize(
    "market,industry",
    [
        ("CN", classification("881155.TI")),  # 银行缺国内曲线和信用条件，不机械取反。
        ("CN", classification("881101.TI")),  # 种植缺价格、成本和政策数据。
        ("US", classification("Farm Products", "Consumer Defensive")),
        ("US", classification("Agricultural Inputs", "Basic Materials")),
        ("US", classification("Unknown", "Technology")),
        ("HK", classification("Software—Application", "Technology")),
        ("CN", None),
    ],
)
def test_unknown_or_unproven_classifications_leave_macro_missing(market, industry):
    result = adapt(background(0), industry, market)
    signal = v2.evaluate("macro", result)
    assert signal["strength"] is None and signal["contribution"] is None
    assert signal["status"] == "unavailable" and signal["reasons"]
    assert v2.evaluate("macro", background(100))["strength"] is None  # no raw-risk fallback


def test_factor_coverage_preserves_missing_neutral_and_zero_semantics():
    industry = classification("Software—Application", "Technology")
    assert adapt(dict(risk_score=100), industry, "US")["adaptation_score"] is None  # 50% <65%
    result = adapt(dict(risk_score=100, states=dict(credit="HEALTHY")), industry, "US")
    assert result["profiles"][0]["coverage"] == pytest.approx(0.7)
    assert result["adaptation_score"] == 100  # missing rates redistributed within profile
    assert result["profiles"][0]["missing_factors"] == ["美债价格趋势"]
    neutral = adapt(background(50, "NEUTRAL", "NEUTRAL"), industry, "US")
    assert neutral["adaptation_score"] == 50
    zero = adapt(background(0), industry, "US")
    assert zero["adaptation_score"] == 0 and v2.evaluate("macro", zero)["status"] == "negative"
    assert adapt(background(float("nan")), industry, "US")["adaptation_score"] is None
    assert adapt(background(True), industry, "US")["adaptation_score"] is None


def test_profiles_are_deduplicated_and_unknown_membership_is_not_cherry_picked():
    data = dict(
        industries=[dict(industry_code="881271.TI"), dict(industry_code="884295.TI"), dict(industry_code="881134.TI")]
    )
    original = deepcopy(data)
    result = adapt(background(20), data, "CN")
    assert len(result["profiles"]) == 2
    assert result["adaptation_score"] == 44  # average(26,62), not duplicated growth
    assert data == original
    data["industries"].append(dict(industry_code="UNKNOWN"))
    assert adapt(background(20), data, "CN")["adaptation_score"] is None


def test_explanations_reconcile_and_rule_coefficients_bound_scores():
    for profile in PROFILES.values():
        assert 0 < sum(abs(c) for c in profile.coefficients.values()) <= 1
    result = adapt(background(20, "HEALTHY", "EASING"), classification("Software—Application", "Technology"), "US")
    for p in result["profiles"]:
        assert 50 + sum(t["contribution"] for t in p["terms"]) == pytest.approx(p["strength"])
    assert result["adaptation_score"] == 60
    assert profile_for("US", dict(industry_code="Biotechnology", sector="Healthcare")) == "us_growth"
    assert profile_for("CN", dict(industry_code="881135.TI")) is None  # 近似消费ETF不能推出防御风格。


def test_unavailable_macro_redistributes_to_other_dimensions_and_keeps_daily_cap():
    signals = {key: v2.evaluate(key) for key in v2.WEIGHTS}
    signals["macro"] = v2.evaluate("macro", adapt(background(), None, "US"))
    signals["trend"] = v2.evaluate("trend", dict(alpha_score=80, state="TRENDING"))
    signals["etf"] = v2.evaluate("etf", dict(etfs=[dict(composite_score=80)]))
    result = v2.aggregate(signals)
    assert result["confluence_score"] == 80 and result["available_weight"] == 50
    assert result["eligible"] and result["signals"]["macro"]["normalized_weight"] is None
    assert v2.rules()["max_signals"] == 10 and v2.WEIGHTS["macro"] == 15
