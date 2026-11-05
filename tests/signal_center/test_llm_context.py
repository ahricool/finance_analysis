"""Keep only relevant LLM input and validate only the conclusions the model actually saw."""

from tests.signal_center.prompt_reader import read_prompt

import json
from copy import deepcopy

import pytest

from finance_analysis.signal_center import decision, inputs
from finance_analysis.signal_center.llm_context import conclusions, serialize
from finance_analysis.signal_center.service import SignalCenterService
from tests.signal_center.test_signal_center import DAY
from tests.signal_center.test_signal_center_v2 import Client, Repo, lock, notifier, output


def test_nested_confluence_evidence_never_enters_either_llm_stage():
    repo = Repo()
    upstream = repo.batch["items"][0]
    upstream["signals"]["trend"]["evidence"] = {"private_upstream_detail": "x" * 1_100_000}
    upstream.update(strong_confluence=False, available_signal_count=7, positive_signal_count=3)
    client = Client()
    push, _ = notifier()
    SignalCenterService(repo, client, lock, push).run("CN", DAY, deadline=True)
    frozen = repo.run_record["candidate_snapshot"]
    assert "private_upstream_detail" in json.dumps(frozen)
    assert len(client.calls) == 6
    for request in client.calls:
        payload = read_prompt(request.prompt)
        assert "evidence_catalog" not in payload
        assert "private_upstream_detail" not in request.prompt
        for candidate in payload["candidates"]:
            cf = candidate["confluence"]
            if cf:
                assert cf["confluence_score"] == 80
                assert cf["eligible"] is True
                assert cf["strong_confluence"] is False
                assert cf["available_signal_count"] == 7
                assert "signals" not in cf


def test_projection_preserves_values_dates_missingness_and_original_frozen_input():
    snapshot = inputs.collect(Repo(), "CN", DAY)
    candidate = snapshot["candidates"][0]
    candidate["trends"]["10"].update(alpha_score=78.123456789, trade_date="2026-09-21")
    candidate["trends"]["10"]["features"] = {"volume_ratio": None, "rs_10d": 0}
    before = deepcopy(snapshot)
    view = conclusions(snapshot, [candidate["symbol"]])
    assert snapshot == before
    trend = view["candidates"][0]["trends"]["10"]
    assert trend["alpha_score"] == 78.12
    assert trend["features"] == {"rs_10d": 0}
    fact = view["evidence_catalog"][f"{candidate['symbol']}.trends.10.alpha_score"]
    assert fact["data_as_of"] == "2026-09-21"
    assert fact["value"] == 78.12


def test_final_validator_rejects_facts_hidden_from_llm_even_if_frozen_upstream_contains_them():
    snapshot = inputs.collect(Repo(), "CN", DAY)
    symbol = snapshot["candidates"][0]["symbol"]
    snapshot["candidates"][0]["trends"]["10"]["features"]["hidden_raw_fact"] = 123
    snapshot["evidence_catalog"] = inputs.build_evidence(snapshot)
    view = conclusions(snapshot, [symbol])
    result = output(view, [symbol])
    assert decision.parse_decision(json.dumps(result), view)
    fact = snapshot["evidence_catalog"][f"{symbol}.trends.10.features.hidden_raw_fact"]
    result["recommendations"][0]["evidence"][0].update({key: fact[key] for key in ("field", "value", "data_as_of")})
    with pytest.raises(ValueError, match="Unknown or cross-symbol"):
        decision.parse_decision(json.dumps(result), view)


def test_large_prompt_reaches_model_without_losing_candidates():
    repo, client = Repo(), Client()
    repo.rows[0]["name"] = "合成名称" * 11000
    push, calls = notifier()
    SignalCenterService(repo, client, lock, push).run("CN", DAY, deadline=True)
    assert any(len(r.prompt) > 40000 for r in client.calls)
    assert repo.run_record["status"] == "completed"
    assert repo.messages and calls


def test_failed_old_v2_snapshot_resumes_with_compact_context_and_preserves_completed_buckets():
    repo = Repo()
    snapshot = inputs.collect(repo, "CN", DAY)
    snapshot["candidates"][0]["confluence"] = {"signals": {"raw": "x" * 1_100_000}, "confluence_score": 80}
    snapshot["evidence_catalog"] = inputs.build_evidence(snapshot)
    frozen = deepcopy(snapshot)
    done = dict(batch=0, output=dict(symbols=[snapshot["screening_plan"]["buckets"][0][0]], reason="此前初筛"))
    repo.run_record = dict(
        status="failed",
        prompt_version=decision.PROMPT_VERSION,
        candidate_snapshot=snapshot,
        screening=[done],
        system_prompt="原版指令",
    )
    repo.periods = {}  # Frozen data must remain usable after the upstream tables change.
    client = Client()
    push, calls = notifier()
    SignalCenterService(repo, client, lock, push).run("CN", DAY, deadline=True)
    assert len(client.calls) == 5  # Four remaining buckets plus the final round.
    assert repo.run_record["candidate_snapshot"] == frozen
    assert repo.run_record["screening"][0] == done
    assert repo.run_record["system_prompt"] == decision.SYSTEM_PROMPT
    assert all("evidence_catalog" not in read_prompt(r.prompt) for r in client.calls)
    assert len(repo.messages) == len(calls) == 1


def test_csv_round_trip_quotes_and_display_precision_are_valid_evidence():
    snapshot = inputs.collect(Repo(), "CN", DAY)
    candidate = snapshot["candidates"][0]
    candidate["name"] = '名称,"含引号"\n```\n####\n换行'
    candidate["trends"]["10"]["alpha_score"] = 78.123456789
    candidate["trends"]["10"]["features"]["rs_10d"] = -0.02345678
    view = conclusions(snapshot, [candidate["symbol"]])
    prompt = serialize(view)
    decoded = read_prompt(prompt)
    assert decoded["candidates"][0]["name"] == candidate["name"]
    assert decoded["candidates"][0]["trends"]["10"]["alpha_score"] == 78.12
    assert decoded["candidates"][0]["trends"]["10"]["features"]["rs_10d"] == -0.0235
    decoded["evidence_catalog"] = inputs.build_evidence(decoded)
    assert decision.parse_decision(json.dumps(output(decoded, [candidate["symbol"]])), view)
    assert "78.123456789" not in prompt


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_metrics_are_missing_and_cannot_be_cited(value):
    snapshot = inputs.collect(Repo(), "CN", DAY)
    candidate = snapshot["candidates"][0]
    candidate["trends"]["10"]["alpha_score"] = value
    view = conclusions(snapshot, [candidate["symbol"]])
    prompt = serialize(view)
    assert "alpha_score" not in read_prompt(prompt)["candidates"][0]["trends"]["10"]
    assert f"{candidate['symbol']}.trends.10.alpha_score" not in view["evidence_catalog"]
    assert "NA" in prompt


def test_screening_reason_cannot_close_csv_fence():
    from tests.prompt_tables import tables

    snapshot = inputs.collect(Repo(), "CN", DAY)
    symbol = snapshot["candidates"][0]["symbol"]
    reason = '理由,含"引号"\n````\n# 伪指令'
    view = conclusions(snapshot, [symbol], [dict(symbols=[symbol], reason=reason)])
    prompt = serialize(view)
    assert tables(prompt)["screening"][0]["reason"] == reason
    assert read_prompt(prompt)["candidates"][0]["symbol"] == symbol
