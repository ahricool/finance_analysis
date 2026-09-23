"""0062 final schema: LLM state instead of Google holdings / strategy state."""

from alembic.config import Config
from alembic.script import ScriptDirectory

from finance_analysis.core.paths import PROJECT_ROOT  # pragma: allowlist secret
from finance_analysis.database.models.trade_engine import TradeLLMState, TradeSignalRow  # pragma: allowlist secret


def test_alembic_head_is_0064():
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0068_us_postmarket_sync"


def test_0062_creates_llm_state_not_google_or_strategy_state():
    text = (PROJECT_ROOT / "alembic" / "versions" / "0062_holdings_portfolio_risk.py").read_text(encoding="utf-8")
    assert 'create_table(\n        "trade_llm_state"' in text or '"trade_llm_state"' in text
    assert "holding_source" not in text
    assert "trade_strategy_state" not in text
    assert "WARNING" not in text
    assert TradeLLMState.__tablename__ == "trade_llm_state"
    columns = {column.name for column in TradeLLMState.__table__.columns}
    assert columns == {
        "id",
        "uid",
        "market",
        "summary",
        "last_decision",
        "last_decision_at",
        "created_at",
        "updated_at",
    }
    checks = [
        str(getattr(item, "sqltext", ""))
        for item in TradeSignalRow.__table__.constraints
        if item.__class__.__name__ == "CheckConstraint"
    ]
    assert any("BUY" in item and "WARNING" not in item for item in checks)
