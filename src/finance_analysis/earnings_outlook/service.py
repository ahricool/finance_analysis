"""Earnings-only orchestration; no strategy, notifications or price-history writes."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.earnings_outlook import EarningsOutlookRepository
from finance_analysis.llm import LLMClient, LLMRequest
from finance_analysis.llm.json_parse import parse_llm_json_response
from .config import OutlookConfig, PROMPT_VERSION
from .context import ContextCollector, consensus, raw_facts
from .prompts import RESEARCH, OUTLOOK
from .rules import (
    NY,
    digest,
    schedule,
    event_window,
    released,
    clean_research,
    normalize_prediction,
    timestamp,
    comparable,
    review_prediction,
    trading_days,
)
from .universe import resolve_members

logger = logging.getLogger(__name__)


def parse_json_object(text):
    value = parse_llm_json_response(text)
    if not isinstance(value, dict) or not value:
        raise ValueError("Expected a nonempty earnings JSON object")
    return value


def json_value(value):
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


class EarningsOutlookService:
    def __init__(self, repo=None, llm=None, collector=None, resolver=None, config=None, clock=utc_now):
        self.repo = repo or EarningsOutlookRepository()
        self.llm = llm or LLMClient()
        self.collector = collector or ContextCollector(self.repo)
        self.resolver = resolver
        self.config = config or OutlookConfig.from_env()
        self.clock = clock

    def run(self, stage="daily", event_id=None):
        if stage not in {"daily", "final", "manual"}:
            raise ValueError("Unknown earnings stage")
        now = self.clock()
        members = resolve_members(self.resolver)  # Empty/failed membership is a task failure, never broader fallback.
        today = now.astimezone(NY).date()
        if stage == "final":
            days = trading_days(today, today + timedelta(days=14))
            if today not in days:
                return {"status": "skipped", "reason": "非美股交易日"}
            target = next(d for d in days if d > today)
            events = self.repo.events(target, target)
            events.sort(key=lambda e: (e.market_session != "bmo", e.id))
        elif event_id is not None:
            event = self.repo.event(event_id)
            if not event:
                raise ValueError("Earnings event not found")
            events = [event]
        else:
            events = self.repo.events(today, today + timedelta(days=self.config.lookahead_days))
        # Reconcile historical applicability even for removed members, without deleting versions.
        events = [e for e in events if e.calendar_type == "earnings" and e.market == "US"]
        public = self.collector.public(now) if events else {}

        def process(event):
            try:
                return self.refresh(event.id, stage, members, public)
            except Exception as exc:
                logger.exception("Earnings outlook failed for event %s", event.id)
                return dict(event_id=event.id, status="failed", error=str(exc))

        with ThreadPoolExecutor(max_workers=self.config.concurrency) as pool:
            results = list(pool.map(process, events))
        if results and all(r["status"] == "failed" for r in results):
            raise RuntimeError("All earnings outlook events failed; see event state and task logs")
        return dict(stage=stage, results=results)

    def refresh(self, event_id, stage, members, public):
        with self.repo.lock(event_id) as lock:
            if not lock.acquired:
                return dict(event_id=event_id, status="busy")
            # A cross-worker semaphore bounds external research, including manual requests.
            slot = None
            for n in range(self.config.concurrency):
                candidate = self.repo.slot(n)
                if candidate.acquire():
                    slot = candidate
                    break
            if slot is None:
                return dict(event_id=event_id, status="busy", reason="research concurrency limit")
            try:
                return self._refresh(event_id, stage, members, public)
            except Exception as exc:
                # The successful projection/pointer is intentionally untouched.
                self.repo.mark(event_id, "failed", str(exc)[:1000])
                raise
            finally:
                slot.release()

    def _refresh(self, event_id, stage, members, public):
        now = self.clock()
        event = self.repo.event(event_id)
        member = members.get(event.symbol)
        if not member:
            self.repo.mark(event_id, "ineligible")
            return dict(event_id=event_id, status="ineligible")
        window = event_window(event)
        stamp = digest(schedule(event))
        state = self.repo.state(event_id)
        if released(event, now, window) or (state and state.frozen_schedule_hash == stamp):
            self.repo.mark(event_id, "frozen", frozen_schedule_hash=stamp)
            return dict(event_id=event_id, status="frozen")
        if event.event_date > now.astimezone(NY).date() + timedelta(days=self.config.lookahead_days):
            return dict(event_id=event_id, status="skipped", reason="outside research window")
        # Cache invalidates on identity, schedule, expectations, or structured guidance changes, not quote changes.
        cache_key = digest(
            dict(
                member=member["instrument_id"],
                event_id=event_id,
                schedule=schedule(event),
                consensus={
                    k: {f: v for f, v in c.items() if f != "observed_at"} if c else None
                    for k, c in consensus(event).items()
                },
                guidance=raw_facts(event).get("guidance"),
                version=PROMPT_VERSION,
            )
        )
        research = self.repo.cached_research(event_id, cache_key, now)
        if (
            stage != "manual"
            and research
            and self.repo.completed(event_id, stage, now.astimezone(NY).date(), stamp, research.id)
        ):
            return dict(event_id=event_id, status="cached")
        self.repo.mark(event_id, "processing")
        context = self.collector.collect(event, member, now, window, public)
        now = self.clock()  # Freeze after deterministic collection, before any research call.
        if released(self.repo.event(event_id), now, window):
            self.repo.mark(event_id, "frozen", frozen_schedule_hash=stamp)
            return dict(event_id=event_id, status="frozen")
        context["data_cutoff"] = now.isoformat()
        context["tolerance"] = vars(self.config)
        if research is None:
            result = self.llm.complete_text(
                LLMRequest(
                    prompt=json.dumps(context, ensure_ascii=False, default=str),
                    system_prompt=RESEARCH,
                    call_type="earnings_research",
                    web_search=True,
                    prefer_search=True,
                ),
                validator=parse_json_object,
            )
            bundle = clean_research(parse_json_object(result.text), now, self.clock())
            proof = result.search_evidence or dict(status="unverified", requested=True, configured_support=False)
            # Claims without transport confirmation are not admissible new external facts.
            if proof["status"] != "confirmed":
                bundle = {
                    **bundle,
                    "unverified_sources": bundle["sources"],
                    "sources": [],
                    "facts": [],
                    "conflicts": [],
                    "publication_unknown": False,
                    "consensus": {},
                }
            research = self.repo.save_research(
                event_id=event_id,
                instrument_id=member["instrument_id"],
                cache_key=cache_key,
                bundle=bundle,
                search_evidence=proof,
                model=result.model,
                backend=result.backend,
                prompt_version=PROMPT_VERSION,
                created_at=self.clock(),
                data_cutoff=now,
                expires_at=now + timedelta(hours=self.config.research_ttl_hours),
            )
        bundle = research.bundle
        sources = {s["source_id"]: s for s in bundle.get("sources", [])}
        for metric in ("eps", "revenue"):
            candidate = bundle.get("consensus", {}).get(metric)
            if not candidate or not candidate.get("selection_reason"):
                continue
            cited = candidate.get("source_ids", [])
            at = timestamp(candidate.get("as_of"))
            if (
                cited
                and all(s in sources and sources[s]["publication_known"] for s in cited)
                and at
                and now - timedelta(days=30) <= at <= now
                and comparable(candidate, event.reporting_period, metric)
            ):
                context["consensus"][metric] = candidate
        if any(
            f.get("kind") == "reported"
            and f.get("quarter") == event.reporting_period
            and any(
                sources[s].get("source_type") in {"official", "official_guidance"} and sources[s]["publication_known"]
                for s in f["source_ids"]
            )
            for f in bundle.get("facts", [])
        ):
            self.repo.mark(event_id, "frozen", "可信资料表明财报已公布", frozen_schedule_hash=stamp)
            return dict(event_id=event_id, status="frozen")
        context["guidance_evidence"] = (
            context.get("guidance_evidence")
            or [f for f in bundle.get("facts", []) if f.get("kind") == "guidance"]
            or None
        )
        stale_consensus = any(
            not timestamp(c.get("as_of")) or now - timestamp(c["as_of"]) > timedelta(days=30)
            for c in context["consensus"].values()
            if c
        )
        context["evidence_limited"] = bool(
            stale_consensus or bundle.get("publication_unknown") or bundle.get("conflicts")
        )
        context["operating_evidence"] = [
            f for f in bundle.get("facts", []) if f.get("kind") in {"guidance", "opportunity", "risk", "analyst"}
        ]
        context["run_date"] = str(now.astimezone(NY).date())
        context["research_id"] = research.id
        context = json_value(context)
        analysis_bundle = {k: v for k, v in bundle.items() if k != "unverified_sources"}
        frozen = dict(context=context, research=analysis_bundle)
        hash_context = {k: v for k, v in context.items() if k != "data_cutoff"}
        input_hash = digest(dict(context=hash_context, research=bundle, stage=stage, version=PROMPT_VERSION))
        if self.repo.find_input(event_id, stage, input_hash):
            # Same actual input, including quote time/price, cannot create another successful version.
            self.repo.mark(event_id, "success")
            return dict(event_id=event_id, status="cached")
        # Recheck after research and immediately before the second paid call.
        fresh = self.repo.event(event_id)
        if digest(schedule(fresh)) != stamp or released(fresh, self.clock(), window):
            self.repo.mark(event_id, "frozen" if released(fresh, self.clock(), window) else "superseded")
            return dict(event_id=event_id, status="frozen_or_changed")
        result = self.llm.complete_text(
            LLMRequest(
                prompt=json.dumps(frozen, ensure_ascii=False), system_prompt=OUTLOOK, call_type="earnings_outlook"
            ),
            validator=parse_json_object,
        )
        prediction = normalize_prediction(parse_json_object(result.text), context, self.config)
        # Membership may change during a long external call. Never publish an ineligible prediction.
        if event.symbol not in resolve_members(self.resolver):
            self.repo.mark(event_id, "ineligible")
            return dict(event_id=event_id, status="ineligible")
        generated = self.clock()
        expires = min(generated + timedelta(hours=24), window["cutoff"])
        summary = {
            k: v
            for k, v in prediction.items()
            if k
            not in {"scenarios", "missing_data", "uncertainties", "tolerance", "earnings_reason", "reaction_reason"}
        }
        summary.update(
            earnings_high=prediction["earnings_confidence"] >= 8
            and all(prediction[m]["judgment"] != "unknown" for m in ("eps", "revenue")),
            reaction_high=prediction["reaction_confidence"] >= 8
            and not prediction["provisional"]
            and prediction["response_direction"] != "uncertain",
            generated_at=generated.isoformat(),
            expires_at=expires.isoformat(),
            release_cutoff=window["cutoff"].isoformat(),
            stage=stage,
            search_status=research.search_evidence["status"],
            data_cutoff=now.isoformat(),
        )
        prediction_id = self.repo.save_prediction(
            summary=summary,
            event_id=event_id,
            instrument_id=member["instrument_id"],
            research_id=research.id,
            schedule_hash=stamp,
            input_hash=input_hash,
            stage=stage,
            context=context,
            prediction=prediction,
            model=result.model,
            backend=result.backend,
            prompt_version=PROMPT_VERSION,
            created_at=generated,
            data_cutoff=now,
            release_cutoff=window["cutoff"],
            expires_at=expires,
            target_trading_date=window["target_trading_date"],
        )
        return dict(event_id=event_id, status="success", prediction_id=prediction_id)

    def review(self):
        now = self.clock()
        results = []
        for version in self.repo.pending_reviews():
            try:
                result = self._review_one(version, now)
                if result:
                    results.append(result)
            except Exception as exc:
                logger.exception("Earnings review failed for event %s", version.event_id)
                results.append(dict(event_id=version.event_id, status="failed", error=str(exc)))
        return dict(results=results)

    def _review_one(self, version, now):
        with self.repo.lock(version.event_id) as lock:
            if not lock.acquired:
                return None
            event = self.repo.event(version.event_id)
            if digest(schedule(event)) != version.schedule_hash:
                self.repo.mark(event.id, "superseded")
                return None
            state = self.repo.state(event.id)
            previous = state.actual if state else None
            same_version = previous and previous.get("prediction_id") == version.id
            if same_version and previous.get("status") == "completed":
                return None
            actual = self.collector.actual(event, version, now)
            if same_version:
                for metric in ("eps", "revenue", "ohlc"):
                    if actual.get(metric) is None:
                        actual[metric] = previous.get("actual", {}).get(metric)
            review = review_prediction(version.prediction, actual, version.context)
            review.update(prediction_id=version.id, reviewed_at=now.isoformat())
            self.repo.mark(event.id, "frozen", actual=json_value(review))
            return dict(event_id=event.id, status=review["status"])
