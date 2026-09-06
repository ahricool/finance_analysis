"""Atomic upsert of structured premarket news judgments."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from finance_analysis.database.models.news import NewsIntel
from finance_analysis.database.models.news_analysis import NewsAnalysis
from finance_analysis.database.session import DatabaseManager

PROMPT_VERSION = "premarket-v1"


def importance_from_score(score):
    return "critical" if score >= 9 else "high" if score >= 7 else "normal" if score >= 4 else "low"


class NewsAnalysisRepo:
    def __init__(self, db=None):
        self.db = db or DatabaseManager.get_instance()

    def persist_premarket(self, important_news, impact_results, *, model, analyzed_at):
        impacts = {item.get("news_id_or_url"): item for item in impact_results}

        def write(session):
            count = 0
            insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
            for item in important_news:
                key = item.get("news_id_or_url")
                news_id = session.execute(select(NewsIntel.id).where(NewsIntel.url == key)).scalar_one_or_none()
                if news_id is None:
                    continue  # Never persist a hallucinated source identifier.
                impact = impacts.get(key, {})
                score = max(0, min(10, int(item.get("importance_score", 0))))
                values = dict(
                    news_intel_id=news_id,
                    analysis_type="premarket",
                    importance_score=score,
                    importance_reason=item.get("importance_reason"),
                    event_type=item.get("event_type"),
                    time_sensitivity=item.get("time_sensitivity"),
                    importance_confidence=item.get("confidence"),
                    impact=impact.get("impact"),
                    impact_score=impact.get("impact_score"),
                    impact_reason=impact.get("reason"),
                    impact_confidence=impact.get("confidence"),
                    related_symbols=list(
                        dict.fromkeys([*(item.get("related_symbols") or []), *(impact.get("related_symbols") or [])])
                    ),
                    watch_points=impact.get("watch_points") or [],
                    risk_notes=impact.get("risk_notes") or [],
                    importance=importance_from_score(score),
                    actionability="watch" if score >= 7 else "none",
                    model=model,
                    prompt_version=PROMPT_VERSION,
                    analyzed_at=analyzed_at,
                    updated_at=analyzed_at,
                )
                session.execute(
                    insert(NewsAnalysis)
                    .values(**values)
                    .on_conflict_do_update(index_elements=["news_intel_id", "analysis_type"], set_=values)
                )
                count += 1
            return count

        return self.db._run_write_transaction("news_analysis.upsert", write)
