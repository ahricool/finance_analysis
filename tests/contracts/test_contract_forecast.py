from finance_analysis.contracts.forecast import contract_window
from finance_analysis.minute_forecast.models import LIVE_HORIZON, MINUTE_MS


def test_contract_window_crosses_utc_midnight_and_requires_confirmed_contiguous_history():
    minute = 86_400_000 * 20000
    bars = [dict(timestamp=minute - i * MINUTE_MS, open=2, low=1, high=3, close=2, volume=3,
                 turnover=6, closed=True) for i in range(1, 21)]
    window = contract_window("BTCUSDT", bars, minute)
    assert window.timezone == "UTC" and window.bars[-1].timestamp == minute - MINUTE_MS
    assert window.targets == [minute + i * MINUTE_MS for i in range(LIVE_HORIZON)]
    bars[6]["closed"] = False
    assert contract_window("BTCUSDT", bars, minute) is None


def test_personal_favorites_are_isolated_and_idempotent():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from finance_analysis.database.models.contracts import FuturesContract
    from finance_analysis.database.models.user import User
    from finance_analysis.interfaces.api.v1.endpoints.crypto import favorite, favorites
    from finance_analysis.interfaces.api.v1.schemas.contracts import ContractFavoriteUpdate

    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    FuturesContract.__table__.create(engine)
    with Session(engine) as db:
        alice, bob = [User(username=name, email=name, role="user", extra={"gender": "unknown"})
                      for name in ("Alice", "Bob")]
        db.add_all([alice, bob, FuturesContract(symbol="BTCUSDT", category="COIN")])
        db.commit()
        for _ in range(2):
            assert favorite("BTCUSDT", ContractFavoriteUpdate(enabled=True), alice, db) == ["BTCUSDT"]
        assert favorites(bob) == []
        assert alice.extra["gender"] == "unknown"
        assert favorite("BTCUSDT", ContractFavoriteUpdate(enabled=False), alice, db) == []
