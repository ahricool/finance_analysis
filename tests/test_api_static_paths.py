# -*- coding: utf-8 -*-
"""Tests for FastAPI static directory wiring."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.app import create_app


def _write_frontend_bundle(static_dir: Path) -> None:
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(
        '<!doctype html><html><body><div id="root">ok</div>'
        '<script type="module" src="/assets/index-abc.js"></script></body></html>',
        encoding="utf-8",
    )
    (assets_dir / "index-abc.js").write_text("console.log('ok');", encoding="utf-8")


def test_create_app_serves_index_and_assets(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    _write_frontend_bundle(static_dir)

    client = TestClient(create_app(static_dir=static_dir))

    root = client.get("/")
    assert root.status_code == 200
    assert "ok" in root.text

    asset = client.get("/assets/index-abc.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text

    missing = client.get("/assets/missing.js")
    assert missing.status_code == 404


def test_create_app_root_returns_404_when_frontend_missing(tmp_path: Path) -> None:
    static_dir = tmp_path / "empty-static"
    static_dir.mkdir()

    client = TestClient(create_app(static_dir=static_dir))
    response = client.get("/")

    assert response.status_code == 404


def test_api_routes_not_swallowed_by_spa_fallback(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    _write_frontend_bundle(static_dir)

    client = TestClient(create_app(static_dir=static_dir))
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
