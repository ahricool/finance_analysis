"""Freeze inputs, screen the entire union, then choose up to three research signals."""

import json
import logging
from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.signal_center import SignalCenterRepository
from finance_analysis.llm import LLMClient, LLMError
from finance_analysis.llm.types import LLMRequest
from finance_analysis.signal_center import decision as contract
from finance_analysis.signal_center import inputs
from finance_analysis.signal_center.legacy import SignalCenterService as LegacyService, model_identity
from finance_analysis.signal_center.notification import render
from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock

logger = logging.getLogger(__name__)


def no_trade(snapshot):
    return dict(
        market=snapshot["market"],
        signal_date=snapshot["signal_date"],
        decision="NO_TRADE",
        thesis="所有初筛桶均未选出证据充分的候选，本日不交易。",
        no_trade_reason="NO_CLEAR_EDGE",
        evidence=[],
        recommendations=[],
    )


class SignalCenterService:
    def __init__(self, repository=None, client=None, lock_factory=None, notifier=None):
        self.repo = repository if repository is not None else SignalCenterRepository()
        self.client = client if client is not None else LLMClient()
        self.lock_factory = lock_factory or (
            lambda market, day: PostgreSQLAdvisoryLock(
                lock_id=day.toordinal() * 2 + (market == "US"), namespace=20260923, db_manager=self.repo.db
            )
        )
        self.notifier = notifier

    def run(self, market, day, *, deadline=False):
        if market not in {"CN", "US"}:
            raise ValueError("Unsupported market")
        with self.lock_factory(market, day) as lock:
            if not lock.acquired:
                return dict(status="busy")
            run = self.repo.get(market, day)
            if run and run["status"] in {"completed", "skipped"}:
                return dict(status=run["status"], market=market, signal_date=day.isoformat())
            if run and run["prompt_version"] != contract.PROMPT_VERSION:
                # The outer session lock remains held. The legacy path uses a no-op lock to avoid re-entry.
                from contextlib import nullcontext
                from types import SimpleNamespace

                return LegacyService(
                    self.repo, self.client, lambda *_: nullcontext(SimpleNamespace(acquired=True))
                ).run(market, day, deadline=deadline)
            if run is None:
                snapshot = inputs.collect(self.repo, market, day)
                if not deadline and not inputs.ready(snapshot):
                    return dict(status="waiting", source_availability=snapshot["source_availability"])
                enough = inputs.sufficient(snapshot)
                run = self.repo.create(
                    market,
                    day,
                    status="pending" if enough else "skipped",
                    candidate_snapshot=snapshot,
                    prompt_version=contract.PROMPT_VERSION,
                    system_prompt=contract.SYSTEM_PROMPT,
                    prompt=json.dumps(snapshot, ensure_ascii=False, allow_nan=False),
                    error=None if enough else "当日输入不足：需要候选、市场环境和已完成的正式共振批次",
                    completed_at=None if enough else utc_now(),
                )
                if not enough:
                    return dict(status="skipped", reason=run["error"])
            try:
                if run["status"] == "failed":
                    self.repo.finish(market, day, status="pending", error=None)
                final = self.screen(market, day, run)
                prompt = json.dumps(final, ensure_ascii=False, allow_nan=False)
                self.repo.finish(market, day, final_prompt=prompt)
                if final["candidates"]:
                    result = self.client.complete_text(
                        LLMRequest(
                            prompt=prompt,
                            system_prompt=run["system_prompt"],
                            call_type="signal_center",
                            web_search=True,
                            prefer_search=True,
                        ),
                        validator=lambda text: contract.parse_decision(text, final),
                    )
                    proof = getattr(result, "search_evidence", None) or dict(status="unverified", requested=True)
                    fields = dict(
                        model=model_identity(result),
                        backend=f"cli/{result.engine}" if result.backend == "cli" else result.backend,
                        raw_response=result.text,
                    )
                    self.repo.finish(market, day, search_evidence=proof, **fields)
                    analysis = contract.parse_decision(result.text, final, proof)
                else:
                    # No final call can manufacture recommendations after zero selections.
                    analysis = no_trade(final)
                    proof = dict(status="not_requested", requested=False)
                    fields = dict(model=None, backend=None, raw_response=None)
                picks = analysis["recommendations"]
                content = render(market, day, analysis, run["candidate_snapshot"], proof, final.get("screening", []))
                notification_id = self.repo.complete(
                    market,
                    day,
                    notification_content=content,
                    analysis=analysis,
                    decision=analysis["decision"],
                    recommendations=picks,
                    selected_symbol=picks[0]["symbol"] if picks else None,
                    confidence=picks[0]["confidence"] if picks else "low",
                    search_evidence=proof,
                    completed_at=utc_now(),
                    error=None,
                    **fields,
                )
            except Exception as exc:
                error = str(exc) if isinstance(exc, LLMError) else f"LLM synthesis failed ({type(exc).__name__})"
                self.repo.finish(market, day, status="failed", error=error)
                raise
            # Notification persistence is atomic with completion; delivery never changes the saved result.
            if notification_id:
                try:
                    if self.notifier is None:
                        from finance_analysis.notification.service import NotificationService

                        self.notifier = NotificationService()
                    self.notifier.push_existing(
                        content,
                        notification_id=notification_id,
                        route_type="report",
                        dedup_key=f"signal-center:{market}:{day}",
                    )
                except Exception:
                    logger.exception("Signal Center notification push failed")
            return dict(
                status="completed",
                market=market,
                signal_date=day.isoformat(),
                decision=analysis["decision"],
                symbols=[p["symbol"] for p in picks],
            )

    def screen(self, market, day, run):
        snapshot = run["candidate_snapshot"]
        by_symbol = {c["symbol"]: c for c in snapshot["candidates"]}
        audit = list(run.get("screening") or [])
        completed = {a["batch"] for a in audit}
        for index, symbols in enumerate(snapshot["screening_plan"]["buckets"]):
            if not symbols or index in completed:
                continue
            batch = dict(snapshot)
            batch.pop("screening_plan", None)
            batch["candidates"] = [by_symbol[s] for s in symbols]
            batch["evidence_catalog"] = {
                k: v for k, v in snapshot["evidence_catalog"].items() if v["symbol"] is None or v["symbol"] in symbols
            }
            prompt = json.dumps(batch, ensure_ascii=False, allow_nan=False)
            result = self.client.complete_text(
                LLMRequest(
                    prompt=prompt,
                    system_prompt=contract.SCREEN_SYSTEM_PROMPT,
                    call_type="signal_center_screen",
                    web_search=True,
                    prefer_search=True,
                ),
                validator=lambda text: contract.parse_screen(text, symbols),
            )
            audit.append(
                dict(
                    batch=index,
                    prompt=prompt,
                    system_prompt=contract.SCREEN_SYSTEM_PROMPT,
                    prompt_version=run["prompt_version"],
                    output=contract.parse_screen(result.text, symbols),
                    raw_response=result.text,
                    model=model_identity(result),
                    backend=f"cli/{result.engine}" if result.backend == "cli" else result.backend,
                    search_evidence=getattr(result, "search_evidence", {}),
                    created_at=utc_now().isoformat(),
                )
            )
            self.repo.finish(market, day, screening=audit)
        selected = {s for a in audit for s in a["output"]["symbols"]}
        final = dict(snapshot)
        final.pop("screening_plan", None)
        final["candidates"] = [c for c in snapshot["candidates"] if c["symbol"] in selected]
        final["evidence_catalog"] = {
            k: v for k, v in snapshot["evidence_catalog"].items() if v["symbol"] is None or v["symbol"] in selected
        }
        final["screening"] = [a["output"] for a in sorted(audit, key=lambda a: a["batch"])]
        return final
