"""Real isolated SQL storage for preview tests; never connects to application DBs."""

from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.research_preview import ResearchPreview, ResearchPreviewItem
from finance_analysis.database.repositories.research_preview import PreviewRepository


class PreviewDatabase:
    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(self.engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
        for model in (Instrument, ResearchPreview, ResearchPreviewItem):
            model.__table__.create(self.engine)

    def get_session(self):
        return Session(self.engine)

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session, session.begin():
            yield session


def preview_repository():
    return PreviewRepository(PreviewDatabase())
