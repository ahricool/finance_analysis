import os

from finance_analysis.integrations.market_data.providers.longbridge.market import (
    _longbridge_config_kwargs,
    _sanitize_longbridge_env,
)


def test_longbridge_sdk_file_logging_is_not_enabled_automatically(monkeypatch):
    monkeypatch.delenv("LONGBRIDGE_LOG_PATH", raising=False)

    _sanitize_longbridge_env()

    assert "LONGBRIDGE_LOG_PATH" not in os.environ
    assert "log_path" not in _longbridge_config_kwargs()


def test_explicit_longbridge_log_path_is_preserved_for_diagnostics(monkeypatch, tmp_path):
    diagnostic_path = str(tmp_path / "longbridge")
    monkeypatch.setenv("LONGBRIDGE_LOG_PATH", diagnostic_path)

    _sanitize_longbridge_env()

    assert os.environ["LONGBRIDGE_LOG_PATH"] == diagnostic_path
    assert "log_path" not in _longbridge_config_kwargs()
