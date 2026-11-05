"""Lossless fact identity for display only; audit snapshots and input hashes stay separate."""

from copy import deepcopy
from hashlib import sha256
import json

from .context import outlook_context


def project_input(frozen):
    if "context" not in frozen or "research" not in frozen:
        return deepcopy(frozen)
    result = deepcopy(frozen)
    context = result["context"] = outlook_context(result["context"])
    research = result["research"]
    facts, identities = {}, {}

    def register(value):
        # No fuzzy text merge: quarter, basis, timestamps, provenance and conflicts all matter.
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = sha256(canonical.encode()).hexdigest()
        fact_id = "f" + digest[:12]
        if fact_id in identities and identities[fact_id] != canonical:
            fact_id = "f" + digest
        identities[fact_id] = canonical
        facts[fact_id] = {**value, "fact_id": fact_id} if isinstance(value, dict) else dict(fact_id=fact_id, text=value)
        return fact_id

    def references(value):
        if value is None:
            return None
        values = value if isinstance(value, list) else [value]
        return list(dict.fromkeys(register(v) for v in values))

    if "facts" in research:
        research["fact_ids"] = references(research.pop("facts"))
    for field in ("guidance_evidence", "operating_evidence"):
        if field in context:
            context[field.replace("_evidence", "_fact_ids")] = references(context.pop(field))
    result["facts"] = list(facts.values())
    # Retain an explicit unresolved source, never silently drop a provenance reference.
    sources = research.setdefault("sources", [])
    known = {s["source_id"] for s in sources}

    def referenced_sources(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "source_ids" and isinstance(item, list):
                    yield from item
                elif key == "adopted_source_id" and item is not None:
                    yield item
                else:
                    yield from referenced_sources(item)
        elif isinstance(value, list):
            for item in value:
                yield from referenced_sources(item)

    for source_id in list(referenced_sources(result)):
        if source_id not in known:
            sources.append(dict(source_id=source_id, status="unresolved_in_frozen_input"))
            known.add(source_id)
    return result
