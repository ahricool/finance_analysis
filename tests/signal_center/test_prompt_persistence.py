"""Real repository writes retain frozen evidence while unfinished runs refresh their template."""

from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finance_analysis.database.models.signal_center import SignalCenterRun
from finance_analysis.database.repositories.signal_center import SignalCenterRepository


@pytest.fixture
def repository():
    engine = create_engine("sqlite://")
    SignalCenterRun.__table__.create(engine)

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with Session(engine) as session, session.begin():
                yield session

    repo = SignalCenterRepository(DB())
    repo.create(
        "CN", date(2026, 11, 4), status="failed", candidate_snapshot={"candidates": [{"symbol": "TEST.SH"}]},
        prompt_version="signal-center-v2-evidence", system_prompt="original system", prompt="original evidence",
        screening=[{"batch": 0, "output": {"symbols": ["TEST.SH"], "reason": "saved selection"}}],
    )
    yield repo
    engine.dispose()


def test_retry_saves_current_system_and_final_prompt_without_replacing_frozen_input(repository):
    day = date(2026, 11, 4)
    before = repository.get("CN", day)
    repository.finish("CN", day, status="pending", error=None)
    repository.finish("CN", day, final_prompt="compact final tables", system_prompt="current system")
    after = repository.get("CN", day)
    assert after["system_prompt"] == "current system"
    assert after["final_prompt"] == "compact final tables"
    for field in ("candidate_snapshot", "prompt", "prompt_version", "screening"):
        assert after[field] == before[field]


@pytest.mark.parametrize("field", ["candidate_snapshot", "prompt", "prompt_version"])
def test_retry_still_rejects_changes_to_frozen_evidence(repository, field):
    day = date(2026, 11, 4)
    with pytest.raises(ValueError, match="Cannot mutate frozen input"):
        repository.finish("CN", day, system_prompt="current system", **{field: "replacement"})
    assert repository.get("CN", day)["system_prompt"] == "original system"


@pytest.mark.parametrize("status", ["completed", "skipped"])
def test_finished_runs_do_not_accept_prompt_updates(repository, status):
    day = date(2026, 11, 4)
    fields = {"status": status}
    if status == "completed":
        fields.update(decision="NO_TRADE", confidence="low", analysis={"thesis": "no clear edge"})
    repository.finish("CN", day, **fields)
    repository.finish("CN", day, final_prompt="replacement tables", system_prompt="replacement system")
    after = repository.get("CN", day)
    assert after["system_prompt"] == "original system"
    assert after["final_prompt"] is None
