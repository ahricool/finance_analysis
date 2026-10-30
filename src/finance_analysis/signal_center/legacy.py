"""Freeze inputs before LLM; retries reuse evidence and completed decisions never change."""

import json
from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.signal_center import SignalCenterRepository
from finance_analysis.llm import LLMClient, LLMError
from finance_analysis.llm.types import LLMRequest
from finance_analysis.signal_center.prompt import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    parse_decision,
    SCREEN_SYSTEM_PROMPT,
    parse_screen,
)
from finance_analysis.signal_center.snapshot import collect, ready, sufficient
from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock

from finance_analysis.signal_center.context import candidate_context


def model_identity(result):
    return result.model or f"unreported:{result.backend}/{result.engine or 'default'}"


class SignalCenterService:
    def __init__(self, repository=None, client=None, lock_factory=None):
        self.repo = repository if repository is not None else SignalCenterRepository()
        self.client = client if client is not None else LLMClient()
        self.lock_factory = lock_factory or (
            lambda market, day: PostgreSQLAdvisoryLock(
                lock_id=day.toordinal() * 2 + (market == "US"), namespace=20260923, db_manager=self.repo.db
            )
        )

    def run(self, market, day, *, deadline=False):
        if market not in {"CN", "US"}:
            raise ValueError("Unsupported market")
        with self.lock_factory(market, day) as lock:
            if not lock.acquired:
                return dict(status="busy")
            run = self.repo.get(market, day)
            if run and run["status"] in {"completed", "skipped"}:
                return dict(status=run["status"], market=market, signal_date=day.isoformat())
            if run is None:
                snapshot = collect(self.repo, market, day)
                if not deadline and not ready(snapshot):
                    return dict(status="waiting", source_availability=snapshot["source_availability"])
                enough = sufficient(snapshot)
                run = self.repo.create(
                    market,
                    day,
                    status="pending" if enough else "skipped",
                    candidate_snapshot=snapshot,
                    prompt_version=PROMPT_VERSION,
                    system_prompt=SYSTEM_PROMPT,
                    prompt=json.dumps(snapshot, ensure_ascii=False, allow_nan=False),
                    error=None if enough else "当日核心输入不足：需要候选、Trend或Quant正式排名及市场环境",
                    completed_at=None if enough else utc_now(),
                )
                if not enough:
                    return dict(status="skipped", reason=run["error"])
            try:
                if run["status"] == "failed":
                    # Publish recovery before any slow LLM call; keep the frozen evidence and completed buckets.
                    self.repo.finish(market, day, status="pending", error=None)
                final_snapshot = self.screen(market, day, run)
                final_prompt = json.dumps(final_snapshot, ensure_ascii=False, allow_nan=False)
                self.repo.finish(market, day, final_prompt=final_prompt)
                result = self.client.complete_text(
                    LLMRequest(
                        prompt=final_prompt,
                        system_prompt=run["system_prompt"],
                        call_type="signal_center",
                        temperature=0.2,
                        max_tokens=3000,
                        web_search=False,
                    ),
                    validator=lambda text: parse_decision(text, final_snapshot),
                )
                analysis = parse_decision(result.text, final_snapshot)
                self.repo.finish(
                    market,
                    day,
                    status="completed",
                    analysis=analysis,
                    decision=analysis["decision"],
                    selected_symbol=analysis["symbol"],
                    confidence=analysis["confidence"],
                    model=model_identity(result),
                    backend=(f"cli/{result.engine}" if result.backend == "cli" else result.backend),
                    raw_response=result.text,
                    error=None,
                    completed_at=utc_now(),
                )
            except Exception as exc:
                error = str(exc) if isinstance(exc, LLMError) else f"LLM synthesis failed ({type(exc).__name__})"
                self.repo.finish(market, day, status="failed", error=error)
                raise
            return dict(
                status="completed",
                market=market,
                signal_date=day.isoformat(),
                decision=analysis["decision"],
                symbol=analysis["symbol"],
            )

    def screen(self, market, day, run):
        snapshot = run["candidate_snapshot"]
        trend = [c for c in snapshot["candidates"] if "trend" in c["nominated_by"]]
        audit = list(run.get("screening") or [])
        plan = snapshot.get("screening_plan")
        if plan is not None:
            by_symbol = {c["symbol"]: c for c in trend}
            batches = [[by_symbol[symbol] for symbol in bucket] for bucket in plan["buckets"]]
        elif run["prompt_version"] == "signal-center-v1":
            # Resume an already-frozen legacy run without reassigning completed batches.
            batches = [trend[offset : offset + 40] for offset in range(0, len(trend), 40)]
        else:
            raise ValueError("Missing frozen screening plan")
        for index, batch in enumerate(batches):
            if not batch or index < len(audit):
                continue
            evidence = [dict(symbol=c["symbol"], name=c["name"], trend=candidate_context(c)["trend"]) for c in batch]
            prompt = json.dumps(
                dict(
                    market=market,
                    signal_date=day.isoformat(),
                    market_regime=snapshot["market_regime"],
                    candidates=evidence,
                ),
                ensure_ascii=False,
                allow_nan=False,
            )
            symbols = [c["symbol"] for c in batch]
            result = self.client.complete_text(
                LLMRequest(
                    prompt=prompt,
                    system_prompt=SCREEN_SYSTEM_PROMPT,
                    call_type="signal_center_screen",
                    temperature=0.2,
                    max_tokens=2000,
                    web_search=False,
                ),
                validator=lambda text: parse_screen(text, symbols),
            )
            parsed = parse_screen(result.text, symbols)
            audit.append(
                dict(
                    batch=index,
                    prompt=prompt,
                    system_prompt=SCREEN_SYSTEM_PROMPT,
                    prompt_version=run["prompt_version"],
                    output=parsed,
                    raw_response=result.text,
                    model=model_identity(result),
                    backend=(f"cli/{result.engine}" if result.backend == "cli" else result.backend),
                    created_at=utc_now().isoformat(),
                )
            )
            self.repo.finish(market, day, screening=audit)
        selected = {s for a in audit for s in a["output"]["symbols"]}
        final = dict(snapshot)
        final.pop("screening_plan", None)  # Full bucket membership remains in the immutable input only.
        final["candidates"] = [
            candidate_context(c)
            for c in snapshot["candidates"]
            if c["symbol"] in selected or any(s != "trend" for s in c["nominated_by"])
        ]
        final["screening"] = [a["output"] for a in audit]
        return final
