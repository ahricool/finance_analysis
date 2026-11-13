"""Synchronize the public catalog without LLM or securities access."""

from finance_analysis.integrations.polymarket.client import Client
from finance_analysis.prediction_markets.rules import project_event, import_slug


class Service:
    def __init__(self, repo=None, client=None):
        if repo is None:
            from finance_analysis.database.repositories.prediction_markets import Repository

            repo = Repository()
        self.repo, self.client = repo, client or Client()

    def catalog(self, slug=None):
        stats = dict(scanned=0, deduplicated=0, retained=0, excluded=0, updated=0, failed=0)
        seen, successes = set(), 0
        try:
            for raw in self.client.tags():
                self.repo.upsert_tag(raw)
                successes += 1
        except Exception:
            stats["failed"] += 1
        tags = self.repo.tags(admin=True)
        self.repo.reclassify()
        stats.update(official_tags=len(tags), visible_tags=sum(t["visible"] for t in tags))

        def save(raw, manual=False):
            nonlocal successes
            stats["scanned"] += 1
            event = project_event(raw)
            if event["event_id"] in seen:
                stats["deduplicated"] += 1
                return
            outcome = self.repo.upsert_event(event, tags, manual)
            seen.add(event["event_id"])
            stats["excluded" if outcome == "excluded" else "retained"] += 1
            stats["updated"] += outcome == "updated"
            successes += 1

        if slug:
            try:
                save(self.client.event_slug(import_slug(slug)), manual=True)
            except Exception:
                stats["failed"] += 1
        else:
            for tag in tags:
                if not tag["visible"]:
                    continue
                try:
                    for raw in self.client.events(tag["tag_id"]):
                        try:
                            save(raw)
                        except Exception:
                            stats["failed"] += 1
                except Exception:
                    stats["failed"] += 1
        # Explicit status checks: absence, dates and 404 never imply closure.
        for event in self.repo.all_events():
            if event["event_id"] not in seen:
                try:
                    save(self.client.event(event["event_id"]))
                except Exception:
                    stats["failed"] += 1
        stats["status"] = "partial" if stats["failed"] and successes else "failed" if stats["failed"] else "completed"
        return stats
