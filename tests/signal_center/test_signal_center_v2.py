"""V2 union coverage, evidence integrity, abstention, checkpointing and notification boundaries."""

import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from finance_analysis.signal_center import inputs, decision
from finance_analysis.signal_center.service import SignalCenterService
from finance_analysis.signal_center.evaluation import with_evaluations
from tests.signal_center.test_signal_center import Repo as LegacyRepo, DAY, NOW, lock


class Repo(LegacyRepo):
    def __init__(self):
        super().__init__(size=100)
        for r in self.rows:
            r["instrument_type"] = "STOCK"
        self.rows.append(dict(id=101, code="510300.SH", name="沪深300ETF", instrument_type="ETF"))
        self.periods = {p: [dict(r, trend_period=p) for r in self.sources["trend"]] for p in (20, 40, 60)}
        # Disjoint nominations prove the longer periods enter the union independently.
        for index, row in enumerate(self.periods[40]):
            row["rank"] = (index + 60) % 100 + 1
        for index, row in enumerate(self.periods[60]):
            row["rank"] = (index + 40) % 100 + 1
        self.sources["etf"] = [
            dict(
                code="510300.SH",
                instrument_id=101,
                rank=1,
                composite_score=80,
                state="TRENDING",
                trade_date=DAY,
                generated_at=NOW,
            )
        ]
        self.batch = dict(
            trade_date=DAY,
            generated_at=NOW,
            items=[
                dict(
                    code="000100.SH",
                    instrument_id=100,
                    name="100",
                    confluence_score=80,
                    eligible=True,
                    signals={"quant": {"evidence": {"secret_quant": 1}}, "trend": {"status": "positive"}},
                    generated_at=NOW,
                )
            ],
        )
        self.messages = []

    def trend_period(self, market, day, period):
        return deepcopy(self.periods[period])

    def quant(self, *_):
        pytest.fail("V2 must not read Quant")

    def confluence(self, *_):
        return deepcopy(self.batch)

    def complete(self, market, day, *, notification_content, **fields):
        assert self.run_record["status"] not in {"completed", "skipped"}
        self.messages.append(notification_content)
        self.finish(market, day, status="completed", notification_id=1, **fields)
        return 1


def pick(snapshot, symbol):
    facts = [v for v in snapshot["evidence_catalog"].values() if v["symbol"] == symbol][:2]
    return dict(
        symbol=symbol,
        confidence="medium",
        thesis="正式证据支持",
        positive_signals=["趋势支持"],
        risks=["结构转弱"],
        invalidations=["趋势结构被破坏"],
        external_sources=[],
        evidence=[
            dict(
                field=f["field"],
                value=f["value"],
                data_as_of=f["data_as_of"],
                interpretation="支持趋势，但不代表未来收益",
                supports=["positive_signals.0", "invalidations.0"] if index == 0 else ["risks.0"],
            )
            for index, f in enumerate(facts)
        ],
    )


def output(snapshot, symbols=()):
    value = dict(
        market=snapshot["market"],
        signal_date=snapshot["signal_date"],
        decision="BUY" if symbols else "NO_TRADE",
        thesis="根据证据择优，允许不交易",
        no_trade_reason=None if symbols else "NO_CLEAR_EDGE",
        evidence=(
            []
            if symbols
            else [
                dict(
                    next(iter(snapshot["evidence_catalog"].values())),
                    interpretation="该证据不足以确立优势",
                    supports=["thesis"],
                )
            ]
        ),
        recommendations=[pick(snapshot, s) for s in symbols],
    )
    for fact in value["evidence"]:
        fact.pop("symbol", None)
    return value


class Client:
    def __init__(self, empty=False, fail_batch=None, fail_final=False, choose_etf=False):
        self.calls = []
        self.empty, self.fail_batch, self.fail_final, self.choose_etf = empty, fail_batch, fail_final, choose_etf

    def complete_text(self, request, validator):
        self.calls.append(request)
        snapshot = json.loads(request.prompt)
        if request.call_type == "signal_center_screen":
            if len(self.calls) == self.fail_batch:
                raise RuntimeError("screen failed")
            candidates = snapshot["candidates"]
            candidates.sort(key=lambda c: (c["instrument_type"] != "ETF", c["symbol"]))
            result = dict(symbols=[] if self.empty else [c["symbol"] for c in candidates[:3]], reason="按证据选择")
        else:
            if self.fail_final:
                raise RuntimeError("final failed")
            symbols = [c["symbol"] for c in snapshot["candidates"]]
            if self.choose_etf:
                symbols.sort(key=lambda s: s != "510300.SH")
            result = output(snapshot, symbols[:3])
        raw = json.dumps(result, ensure_ascii=False)
        validator(raw)
        return SimpleNamespace(
            text=raw, model="test", backend="api", engine=None, search_evidence=dict(status="confirmed", citations=[])
        )


def notifier():
    calls = []
    return SimpleNamespace(push_existing=lambda *args, **kw: calls.append((args, kw))), calls


def test_union_has_fixed_period_limits_etf_and_all_published_confluence_without_quant():
    snapshot = inputs.collect(Repo(), "CN", DAY)
    candidates = snapshot["candidates"]
    counts = {
        source: sum(source in c["nominated_by"] for c in candidates)
        for source in ("trend20", "trend40", "trend60", "etf", "confluence")
    }
    assert counts == dict(trend20=30, trend40=10, trend60=10, etf=1, confluence=1)
    assert next(c for c in candidates if c["symbol"] == "510300.SH")["instrument_type"] == "ETF"
    assert "secret_quant" not in json.dumps(snapshot)
    assert "quant" not in snapshot["source_availability"]
    buckets = snapshot["screening_plan"]["buckets"]
    assert len(buckets) == 5
    flattened = [s for b in buckets for s in b]
    assert sorted(flattened) == sorted(c["symbol"] for c in candidates)
    assert len(flattened) == len(set(flattened))
    assert max(map(len, buckets)) - min(map(len, buckets)) <= 1


def test_confluence_empty_generation_is_ready_but_missing_or_running_never_freezes_early():
    repo = Repo()
    repo.batch["items"] = []
    assert inputs.ready(inputs.collect(repo, "CN", DAY)) is False  # Industry intentionally missing.
    assert inputs.sufficient(inputs.collect(repo, "CN", DAY))
    repo.batch["generated_at"] = None
    assert not inputs.sufficient(inputs.collect(repo, "CN", DAY))
    repo.batch["generated_at"] = NOW
    repo.deps = {"confluence": {"status": "processing"}}
    snapshot = inputs.collect(repo, "CN", DAY)
    assert snapshot["source_availability"]["confluence"]["status"] == "running"
    assert not inputs.sufficient(snapshot)
    repo.batch["trade_date"] = DAY - timedelta(days=1)
    repo.deps = {}
    assert not inputs.sufficient(inputs.collect(repo, "CN", DAY))


def test_five_buckets_choose_at_most_fifteen_then_three_and_notify_once():
    repo, client = Repo(), Client(choose_etf=True)
    push, calls = notifier()
    service = SignalCenterService(repo, client, lock, push)
    result = service.run("CN", DAY, deadline=True)
    assert len(result["symbols"]) == 3 and "510300.SH" in result["symbols"]
    assert len(client.calls) == 6
    assert all(r.web_search and r.prefer_search for r in client.calls)
    final = json.loads(client.calls[-1].prompt)
    assert len(final["candidates"]) == 15
    assert all(len(a["output"]["symbols"]) <= 3 for a in repo.run_record["screening"])
    assert len(repo.messages) == len(calls) == 1
    assert "510300.SH" in repo.messages[0] and "证据" in repo.messages[0] and "失效条件" in repo.messages[0]
    assert repo.run_record["search_evidence"]["status"] == "confirmed"
    service.run("CN", DAY, deadline=True)
    assert len(client.calls) == 6 and len(repo.messages) == len(calls) == 1


def test_all_empty_screening_is_no_trade_without_an_extra_final_call():
    repo, client = Repo(), Client(empty=True)
    push, _ = notifier()
    SignalCenterService(repo, client, lock, push).run("CN", DAY, deadline=True)
    assert len(client.calls) == 5
    assert repo.run_record["decision"] == "NO_TRADE" and repo.run_record["recommendations"] == []
    assert repo.run_record["analysis"]["no_trade_reason"] == "NO_CLEAR_EDGE"
    assert len(repo.messages) == 1


def test_failed_bucket_resumes_original_union_and_completed_batches():
    repo, client = Repo(), Client(fail_batch=3)
    push, calls = notifier()
    service = SignalCenterService(repo, client, lock, push)
    with pytest.raises(RuntimeError):
        service.run("CN", DAY, deadline=True)
    frozen = deepcopy(repo.run_record["candidate_snapshot"])
    assert len(repo.run_record["screening"]) == 2 and not repo.messages and not calls
    repo.periods = {}  # A retry must not read changed source tables.
    client.fail_batch = None
    service.run("CN", DAY, deadline=True)
    assert repo.run_record["candidate_snapshot"] == frozen
    assert len(client.calls) == 7  # failed call + five successful buckets + final
    assert len(repo.messages) == len(calls) == 1


def test_final_failure_keeps_checkpoints_and_does_not_send_a_message():
    repo, client = Repo(), Client(fail_final=True)
    push, calls = notifier()
    service = SignalCenterService(repo, client, lock, push)
    with pytest.raises(RuntimeError):
        service.run("CN", DAY, deadline=True)
    assert len(repo.run_record["screening"]) == 5 and not repo.messages and not calls
    client.fail_final = False
    service.run("CN", DAY, deadline=True)
    assert len(client.calls) == 7 and len(repo.messages) == len(calls) == 1


def test_push_failure_never_changes_completed_decision():
    repo = Repo()

    def fail(*args, **kwargs):
        raise RuntimeError("push failed")

    service = SignalCenterService(repo, Client(), lock, SimpleNamespace(push_existing=fail))
    assert service.run("CN", DAY, deadline=True)["status"] == "completed"
    assert repo.run_record["status"] == "completed" and len(repo.messages) == 1


@pytest.mark.parametrize(
    "mutation", ["value", "date", "unknown", "duplicate", "other_symbol", "empty_risk", "too_many"]
)
def test_rejects_fabricated_evidence_and_invalid_selections(mutation):
    snapshot = inputs.collect(Repo(), "CN", DAY)
    value = output(snapshot, ["000001.SH"])
    recommendation = value["recommendations"][0]
    fact = recommendation["evidence"][0]
    if mutation == "value":
        fact["value"] = "fabricated"
    elif mutation == "date":
        fact["data_as_of"] = "2020-01-01"
    elif mutation == "unknown":
        fact["field"] = "made_up"
    elif mutation == "duplicate":
        recommendation["evidence"] = [fact, fact]
    elif mutation == "other_symbol":
        replacement = next(f for f in snapshot["evidence_catalog"].values() if f["symbol"] == "000002.SH")
        fact.update({k: replacement[k] for k in ("field", "value", "data_as_of")})
    elif mutation == "empty_risk":
        recommendation["risks"] = [" "]
    else:
        value["recommendations"] = [pick(snapshot, c["symbol"]) for c in snapshot["candidates"][:4]]
    with pytest.raises(ValueError):
        decision.parse_decision(json.dumps(value), snapshot)


def test_external_sources_need_transport_evidence_and_cannot_be_future_dated():
    snapshot = inputs.collect(Repo(), "CN", DAY)
    value = output(snapshot, ["000001.SH"])
    source = dict(url="https://example.com/announcement", title="公告", published_date="2026-09-22", excerpt="公告摘录")
    value["recommendations"][0]["external_sources"] = [source]
    with pytest.raises(ValueError):
        decision.parse_decision(json.dumps(value), snapshot, dict(status="unverified"))
    assert decision.parse_decision(json.dumps(value), snapshot, dict(status="confirmed"))
    source["published_date"] = "2026-09-23"
    with pytest.raises(ValueError):
        decision.parse_decision(json.dumps(value), snapshot, dict(status="confirmed"))


def test_no_trade_requires_reason_and_final_selection_cannot_escape_screening():
    snapshot = inputs.collect(Repo(), "CN", DAY)
    value = output(snapshot)
    value["no_trade_reason"] = None
    with pytest.raises(ValueError):
        decision.parse_decision(json.dumps(value), snapshot)
    value = output(snapshot, ["000001.SH"])
    snapshot["candidates"] = []
    with pytest.raises(ValueError):
        decision.parse_decision(json.dumps(value), snapshot)
    with pytest.raises(ValueError):
        decision.parse_screen(json.dumps(dict(symbols=["a", "b", "c", "d"], reason="x")), ["a", "b", "c", "d"])


def test_multi_pick_evaluations_batch_all_symbols_without_mutating_decision(monkeypatch):
    from datetime import datetime, timezone
    from finance_analysis.signal_center import evaluation

    session = (DAY, datetime(2026, 9, 22, 8, tzinfo=timezone.utc))
    monkeypatch.setattr(evaluation, "session_plan", lambda _: [session] * 10)
    queries = []

    def load(pairs):
        queries.append(pairs)
        return [
            dict(code=s, date=d, open=100, close=110 if s == "A.US" else 90, high=120, low=80, volume=10)
            for s, d in pairs
        ]

    row = dict(
        market="US",
        signal_date=DAY,
        status="completed",
        decision="BUY",
        selected_symbol="A.US",
        recommendations=[dict(symbol=s) for s in ("A.US", "B.US")],
        candidate_snapshot={},
    )
    result = with_evaluations(SimpleNamespace(load_evaluation_bars=load), [row], now=NOW)[0]
    assert len(queries) == 1 and queries[0] == {("A.US", DAY), ("B.US", DAY)}
    assert [p["evaluation"]["horizons"][0]["value"] for p in result["recommendations"]] == pytest.approx([0.1, -0.1])
    assert "evaluation" not in row["recommendations"][0]


def test_industry_still_keeps_top_five_and_three_members_per_group():
    repo = Repo()
    repo.sources["industry"] = [
        dict(code=f"{j:06d}.SH", industry_code=f"I{i}", strength_rank=i, trend_rank=j, trade_date=DAY, generated_at=NOW)
        for i in range(1, 7)
        for j in range(i * 10, i * 10 + 8)
    ]
    snapshot = inputs.collect(repo, "CN", DAY)
    nominated = [c for c in snapshot["candidates"] if "industry" in c["nominated_by"]]
    assert len(nominated) == 15
    assert {r["industry_code"] for c in nominated for r in c["industry"]} == {f"I{i}" for i in range(1, 6)}


def test_missing_confluence_at_deadline_skips_without_calling_llm_or_notifying():
    repo, client = Repo(), Client()
    repo.batch = dict(trade_date=DAY, generated_at=None, items=[])
    push, calls = notifier()
    service = SignalCenterService(repo, client, lock, push)
    assert service.run("CN", DAY)["status"] == "waiting" and repo.run_record is None
    assert service.run("CN", DAY, deadline=True)["status"] == "skipped"
    assert not client.calls and not calls and not repo.messages


def test_old_empty_confluence_manifest_keeps_its_real_date():
    repo = Repo()
    repo.batch.update(trade_date=DAY - timedelta(days=1), items=[])
    source = inputs.collect(repo, "CN", DAY)["source_availability"]["confluence"]
    assert source["status"] == "stale" and source["data_as_of"] == "2026-09-21"


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_final_decision_accepts_zero_to_three_without_filling_slots(count):
    snapshot = inputs.collect(Repo(), "CN", DAY)
    symbols = [c["symbol"] for c in snapshot["candidates"][:count]]
    parsed = decision.parse_decision(json.dumps(output(snapshot, symbols)), snapshot)
    assert len(parsed["recommendations"]) == count


def test_us_ignores_industry_source():
    repo = Repo()
    repo.sources["industry"] = RuntimeError("must not read unsupported source")
    snapshot = inputs.collect(repo, "US", DAY)
    assert snapshot["source_availability"]["industry"]["status"] == "unsupported"
    assert not any("industry" in c["nominated_by"] for c in snapshot["candidates"])


def test_rejects_uncited_claim_and_no_trade_without_evidence():
    snapshot = inputs.collect(Repo(), "CN", DAY)
    value = output(snapshot, ["000001.SH"])
    value["recommendations"][0]["risks"].append("未经引用支持的风险主张")
    with pytest.raises(ValueError, match="Every BUY claim"):
        decision.parse_decision(json.dumps(value), snapshot)
    value = output(snapshot)
    value["evidence"] = []
    with pytest.raises(ValueError, match="NO_TRADE requires"):
        decision.parse_decision(json.dumps(value), snapshot)


def test_http_contract_returns_all_picks_with_typed_evidence_and_separate_evaluations():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finance_analysis.interfaces.api.deps import require_current_user
    from finance_analysis.interfaces.api.v1.endpoints import signal_center as api

    repo = Repo()
    push, _ = notifier()
    SignalCenterService(repo, Client(), lock, push).run("CN", DAY, deadline=True)
    saved = dict(repo.run_record, created_at=NOW)
    reader = SimpleNamespace(
        get=lambda *_: deepcopy(saved), history=lambda *_: [deepcopy(saved)], load_evaluation_bars=lambda _: []
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_repository] = lambda: reader
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    response = TestClient(app).get("/CN/2026-09-22")
    assert response.status_code == 200
    data = response.json()
    assert len(data["recommendations"]) == 3
    for item in data["recommendations"]:
        assert item["evidence"][0]["supports"]
        assert item["evaluation"]["status"] in {"unavailable", "pending"}
    assert data["search_evidence"]["status"] == "confirmed"


def test_numeric_json_evidence_accepts_equivalent_numbers_but_rejects_booleans():
    snapshot = inputs.collect(Repo(), "CN", DAY)
    value = output(snapshot, ["000001.SH"])
    fact = value["recommendations"][0]["evidence"][0]
    assert fact["value"] == 1
    fact["value"] = 1.0
    assert decision.parse_decision(json.dumps(value), snapshot)
    fact["value"] = True
    with pytest.raises(ValueError, match="value mismatch"):
        decision.parse_decision(json.dumps(value), snapshot)
