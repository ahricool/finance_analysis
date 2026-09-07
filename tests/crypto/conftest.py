import pytest
from .helpers import Database, START
from datetime import timedelta
from finance_analysis.database.repositories.crypto import CryptoRepository


@pytest.fixture
def repository():
    return CryptoRepository(Database())


@pytest.fixture(autouse=True)
def fixed_crypto_clock(monkeypatch):
    now = START + timedelta(days=31)
    monkeypatch.setattr("finance_analysis.crypto.service.utc_now", lambda: now)
    monkeypatch.setattr("finance_analysis.database.repositories.crypto.utc_now", lambda: now)
