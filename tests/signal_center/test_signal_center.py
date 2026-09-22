"""Offline contract, freshness, screening and immutable retry tests."""

import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from finance_analysis.signal_center.prompt import parse_decision, parse_screen
from finance_analysis.signal_center.service import SignalCenterService
from finance_analysis.signal_center.snapshot import collect, ready, sufficient

DAY = date(2026, 9, 22)
NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


class Repo:
    def __init__(self, market="CN", size=200):
        self.market = market
        self.rows = [
            {"id": i, "code": f"{i:06d}.SH" if market == "CN" else f"S{i}.US", "name": str(i)}
            for i in range(1, size + 1)
        ]
        self.sources = {
            "trend": [
                dict(
                    instrument_id=r["id"],
                    code=r["code"],
                    rank=r["id"],
                    trade_date=DAY,
                    generated_at=NOW,
                    reference_price=10,
                    features={},
                    rank_change=0,
                    state="TRENDING",
                )
                for r in self.rows
            ],
            "quant": [
                dict(instrument_id=r["id"], universe_rank=n + 1, trade_date=DAY, generated_at=NOW, final_score=0.5)
                for n, r in enumerate(self.rows[-8:])
            ],
            "industry": [],
            "etf": [dict(trade_date=DAY, generated_at=NOW, rank=1)],
            "regime": [dict(trade_date=DAY, generated_at=NOW, source="trend", market_regime="NEUTRAL")],
        }
        self.run_record = None
        self.deps = {}
        self.reads = 0

    def instruments(self, market):
        self.reads += 1
        return self.rows

    def dependencies(self, market, day):
        return self.deps

    def __getattr__(self, key):
        if key in self.sources:

            def source(market, day):
                value = self.sources[key]
                if isinstance(value, Exception):
                    raise value
                return deepcopy(value)

            return source
        raise AttributeError(key)

    def get(self, market, day):
        return deepcopy(self.run_record)

    def create(self, market, day, **fields):
        assert self.run_record is None
        self.run_record = dict(market=market, signal_date=day.isoformat(), **fields)
        return deepcopy(self.run_record)

    def finish(self, market, day, **fields):
        self.run_record.update(deepcopy(fields))


@contextmanager
def lock(*args):
    yield SimpleNamespace(acquired=True)


def output(snapshot, decision="NO_TRADE", symbol=None):
    return dict(
        market=snapshot["market"],
        signal_date=snapshot["signal_date"],
        decision=decision,
        symbol=symbol,
        confidence="medium",
        thesis="证据存在冲突",
        positive_signals=["趋势"],
        risks=["追高"],
        invalidations=["跌破趋势结构"],
    )


class Client:
    def __init__(self, fail_final=False):
        self.calls = []
        self.fail_final = fail_final

    def complete_text(self, request, validator):
        self.calls.append(request)
        payload = json.loads(request.prompt)
        if request.call_type == "signal_center_screen":
            value = dict(symbols=[c["symbol"] for c in payload["candidates"][:2]], reason="初筛")
        else:
            if self.fail_final:
                raise RuntimeError("temporary failure")
            value = output(payload)
        result = json.dumps(value)
        validator(result)
        return SimpleNamespace(text=result, model="test-model", backend="api", engine=None)


def test_trend_top_five_percent_plus_significant_risers_and_quant_top_three():
    repo = Repo()
    repo.sources["trend"][14]["rank_change"] = 80  # rank15, top7.5%, meaningful new entrant
    repo.sources["trend"][79]["rank_change"] = 100  # outside top10%, excluded
    repo.sources["trend"][15]["rank_change"] = -80  # falling out, not a new entrant
    snapshot = collect(repo, "CN", DAY)
    trend = [c for c in snapshot["candidates"] if "trend" in c["nominated_by"]]
    quant = [c for c in snapshot["candidates"] if "quant" in c["nominated_by"]]
    assert len(trend) == 11
    assert len(quant) == 3
    assert "000015.SH" in {c["symbol"] for c in trend}
    assert "000080.SH" not in {c["symbol"] for c in trend}
    assert "000016.SH" not in {c["symbol"] for c in trend}
    assert snapshot["selection_rules"]["trend_top_count"] == 10


def test_industry_diversity_and_union_context_includes_non_nominating_signals():
    repo = Repo()
    repo.sources["industry"] = [
        dict(code=f"{j:06d}.SH", industry_code=f"I{i}", strength_rank=i, trend_rank=j, trade_date=DAY, generated_at=NOW)
        for i in range(1, 7)
        for j in range(i * 10, i * 10 + 8)
    ]
    snapshot = collect(repo, "CN", DAY)
    members = [c for c in snapshot["candidates"] if "industry" in c["nominated_by"]]
    assert len(members) == 15
    assert {r["industry_code"] for c in members for r in c["industry"]} == {f"I{i}" for i in range(1, 6)}
    assert all(c["trend"] is not None for c in members)
    assert len({c["symbol"] for c in snapshot["candidates"]}) == len(snapshot["candidates"])


def test_stale_failed_and_running_sources_are_explicit_and_excluded():
    repo = Repo()
    for row in repo.sources["quant"]:
        row["trade_date"] = DAY - timedelta(days=1)
    repo.sources["industry"] = RuntimeError("unavailable")
    repo.deps = {"etf_rotation": {"status": "processing"}}
    snapshot = collect(repo, "CN", DAY)
    manifest = snapshot["source_availability"]
    assert manifest["quant"]["status"] == "stale"
    assert manifest["quant"]["data_as_of"] == "2026-09-21"
    assert manifest["industry"]["status"] == "failed"
    assert manifest["etf"]["status"] == "running"
    assert snapshot["etf_context"] == []
    assert not ready(snapshot) and sufficient(snapshot)
    assert all(c["quant"] is None for c in snapshot["candidates"])


@pytest.mark.parametrize(
    "mutation",
    [
        {"market": "US"},
        {"signal_date": "2026-09-21"},
        {"symbol": "UNKNOWN.US", "decision": "BUY"},
        {"symbol": "000001.SH"},
        {"decision": "SELL"},
        {"recommendations": []},
        {"thesis": " "},
        {"symbol": "000001.SH", "decision": "BUY", "risks": []},
    ],
)
def test_final_validation_rejects_invalid_decisions(mutation):
    snapshot = collect(Repo(), "CN", DAY)
    value = output(snapshot) | mutation
    with pytest.raises(ValueError):
        parse_decision(json.dumps(value), snapshot)


def test_buy_no_trade_and_fenced_json_are_supported_without_repair():
    snapshot = collect(Repo(), "CN", DAY)
    for value in [output(snapshot), output(snapshot, "BUY", "000001.SH")]:
        assert parse_decision("```json\n" + json.dumps(value) + "\n```", snapshot) == value
    with pytest.raises(ValueError):
        parse_decision("[{}]", snapshot)
    with pytest.raises(ValueError):
        parse_screen('{"symbols":[],"symbols":[],"reason":"a"}', [])
    with pytest.raises(ValueError):
        parse_screen(json.dumps(dict(symbols=["x", "x"], reason="a")), ["x"])
    with pytest.raises(ValueError):
        parse_screen(json.dumps(dict(symbols=["y"], reason="a")), ["x"])


def test_wait_then_partial_deadline_freezes_input_and_completed_is_idempotent():
    repo, client = Repo(), Client()
    service = SignalCenterService(repo, client, lock)
    assert service.run("CN", DAY)["status"] == "waiting"
    assert repo.run_record is None and client.calls == []
    assert service.run("CN", DAY, deadline=True)["decision"] == "NO_TRADE"
    saved = deepcopy(repo.run_record)
    repo.sources["trend"] = []
    assert service.run("CN", DAY, deadline=True)["status"] == "completed"
    assert repo.run_record == saved
    assert [c.call_type for c in client.calls] == ["signal_center_screen"] * 5 + ["signal_center"]
    assert all(c.web_search is False for c in client.calls)


def test_failed_final_reuses_frozen_snapshot_and_completed_screening():
    repo, client = Repo(), Client(fail_final=True)
    service = SignalCenterService(repo, client, lock)
    with pytest.raises(RuntimeError):
        service.run("CN", DAY, deadline=True)
    before = deepcopy(repo.run_record)
    assert before["status"] == "failed" and len(before["screening"]) == 5
    reads = repo.reads
    repo.sources["trend"] = RuntimeError("must not reread")
    client.fail_final = False
    assert service.run("CN", DAY, deadline=True)["status"] == "completed"
    assert repo.reads == reads
    assert repo.run_record["candidate_snapshot"] == before["candidate_snapshot"]
    assert len([c for c in client.calls if c.call_type == "signal_center_screen"]) == 5


def test_core_missing_is_skipped_never_no_trade():
    repo = Repo()
    repo.sources["trend"] = []
    repo.sources["quant"] = []
    client = Client()
    assert SignalCenterService(repo, client, lock).run("CN", DAY, deadline=True)["status"] == "skipped"
    assert repo.run_record.get("decision") is None and not client.calls


def test_us_is_independent_and_industry_unsupported():
    repo = Repo("US")
    snapshot = collect(repo, "US", DAY)
    assert snapshot["source_availability"]["industry"]["status"] == "unsupported"
    assert ready(snapshot)
    assert SignalCenterService(repo, Client(), lock).run("US", DAY)["status"] == "completed"


def test_lock_busy_does_not_read_or_call_llm():
    @contextmanager
    def busy(*args):
        yield SimpleNamespace(acquired=False)

    repo, client = Repo(), Client()
    assert SignalCenterService(repo, client, busy).run("CN", DAY)["status"] == "busy"
    assert repo.reads == 0 and not client.calls


def test_batched_screening_covers_every_top_five_percent_candidate():
    repo, client = Repo(size=1900), Client()
    service = SignalCenterService(repo, client, lock)
    service.run("CN", DAY, deadline=True)
    calls = [json.loads(c.prompt) for c in client.calls if c.call_type == "signal_center_screen"]
    assert [len(c["candidates"]) for c in calls] == [19] * 5
    assert len(repo.run_record["screening"]) == 5
    assert len(json.loads(repo.run_record["final_prompt"])["candidates"]) == 13  # ten screened + Quant3


@pytest.mark.parametrize("size", [0, 1, 3, 5, 6, 51, 210])
def test_five_buckets_distribute_rank_not_symbol_without_loss(size):
    from finance_analysis.signal_center.snapshot import screening_plan

    candidates = [
        dict(symbol=f"{size-rank:06d}.SH", nominated_by=["trend"], trend={"rank": rank}) for rank in range(1, size + 1)
    ]
    plan = screening_plan(list(reversed(candidates)))
    assert plan["bucket_count"] == 5
    assert len(plan["buckets"]) == 5
    by_symbol = {c["symbol"]: c["trend"]["rank"] for c in candidates}
    assert [[by_symbol[s] for s in bucket] for bucket in plan["buckets"]] == [
        list(range(i + 1, size + 1, 5)) for i in range(5)
    ]
    flattened = [s for bucket in plan["buckets"] for s in bucket]
    assert len(flattened) == len(set(flattened)) == size
    sizes = [len(b) for b in plan["buckets"]]
    assert max(sizes) - min(sizes) <= 1


def test_tied_ranks_are_stable_and_nontrend_nominees_stay_out_of_buckets():
    from finance_analysis.signal_center.snapshot import screening_plan

    candidates = [dict(symbol=s, nominated_by=["trend"], trend={"rank": 1}) for s in ["B.US", "A.US"]]
    candidates.append(dict(symbol="Q.US", nominated_by=["quant"], trend=None))
    assert screening_plan(candidates)["buckets"] == [["A.US"], ["B.US"], [], [], []]


def test_empty_buckets_do_not_call_llm():
    repo, client = Repo(size=40), Client()  # Top5% = 2 nominees, three empty buckets.
    SignalCenterService(repo, client, lock).run("CN", DAY, deadline=True)
    assert len([c for c in client.calls if c.call_type == "signal_center_screen"]) == 2
    assert len(repo.run_record["candidate_snapshot"]["screening_plan"]["buckets"]) == 5


def test_failed_bucket_resumes_frozen_plan_and_skips_completed_buckets():
    class FailingClient(Client):
        fail = True

        def complete_text(self, request, validator):
            if self.fail and len(self.calls) == 2:
                raise RuntimeError("third bucket failed")
            return super().complete_text(request, validator)

    repo, client = Repo(size=1900), FailingClient()
    service = SignalCenterService(repo, client, lock)
    with pytest.raises(RuntimeError):
        service.run("CN", DAY, deadline=True)
    frozen = deepcopy(repo.run_record["candidate_snapshot"])
    assert len(repo.run_record["screening"]) == 2
    repo.sources["trend"] = RuntimeError("must not reread")
    client.fail = False
    service.run("CN", DAY, deadline=True)
    assert repo.run_record["candidate_snapshot"] == frozen
    calls = [json.loads(c.prompt) for c in client.calls if c.call_type == "signal_center_screen"]
    assert [[c["symbol"] for c in p["candidates"]] for p in calls] == frozen["screening_plan"]["buckets"]
    assert len(repo.run_record["screening"]) == 5


def test_legacy_frozen_run_retains_original_batches():
    repo, client = Repo(size=1900), Client(fail_final=True)
    snapshot = collect(repo, "CN", DAY)
    snapshot.pop("screening_plan")
    from finance_analysis.signal_center.prompt import SYSTEM_PROMPT

    repo.create(
        "CN",
        DAY,
        status="pending",
        candidate_snapshot=snapshot,
        prompt_version="signal-center-v1",
        system_prompt=SYSTEM_PROMPT,
    )
    service = SignalCenterService(repo, client, lock)
    with pytest.raises(RuntimeError):
        service.run("CN", DAY, deadline=True)
    assert [len(json.loads(c.prompt)["candidates"]) for c in client.calls if c.call_type == "signal_center_screen"] == [
        40,
        40,
        15,
    ]
    assert all(a["prompt_version"] == "signal-center-v1" for a in repo.run_record["screening"])
    client.fail_final = False
    service.run("CN", DAY, deadline=True)
    assert len([c for c in client.calls if c.call_type == "signal_center_screen"]) == 3
