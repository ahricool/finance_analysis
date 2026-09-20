import pytest

from finance_analysis.database.repositories.crypto import CryptoRepository

from .helpers import Database


@pytest.fixture
def repository():
    return CryptoRepository(Database())
