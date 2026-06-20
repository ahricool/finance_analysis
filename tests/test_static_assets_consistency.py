# -*- coding: utf-8 -*-
"""Tests for backend startup static asset self-check in ``api.app``.

Targets the blank-page / "Preparing backend..." regression captured in
GitHub issues #1064, #1065 and #1050: vite produces a fresh ``index.html``
that references ``/assets/index-<hash>.js``, but the packaging step copies a
stale ``static/assets`` directory, so the bundle referenced by ``index.html``
does not exist on disk.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _write_index(static_dir: Path, body: str) -> None:
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "index.html").write_text(body, encoding="utf-8")


def _vite_index(js_name: str, css_name: str) -> str:
    return (
        "<!doctype html><html><head>"
        f'<script type="module" crossorigin src="/assets/{js_name}"></script>'
        f'<link rel="stylesheet" crossorigin href="/assets/{css_name}">'
        "</head><body><div id=\"root\"></div></body></html>"
    )


def test_backend_asset_check_passes_when_assets_match(tmp_path: Path) -> None:
    from fastapi import app as app_module

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "index-abc.js").write_text("// js", encoding="utf-8")
    (assets_dir / "index-abc.css").write_text("/* css */", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    missing = app_module._check_frontend_assets_consistency(static_dir)

    assert missing == []


def test_backend_asset_check_detects_stale_bundle(tmp_path: Path) -> None:
    from fastapi import app as app_module

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "index-OLD.js").write_text("// old", encoding="utf-8")
    (assets_dir / "index-OLD.css").write_text("/* old */", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-NEW.js", "index-NEW.css"))

    missing = app_module._check_frontend_assets_consistency(static_dir)

    assert sorted(missing) == ["/assets/index-NEW.css", "/assets/index-NEW.js"]


def test_backend_asset_check_returns_empty_when_index_missing(tmp_path: Path) -> None:
    from fastapi import app as app_module

    static_dir = tmp_path / "static"
    static_dir.mkdir()

    missing = app_module._check_frontend_assets_consistency(static_dir)

    assert missing == []


def test_backend_startup_check_logs_when_bundle_inconsistent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fastapi import app as app_module

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    _write_index(static_dir, _vite_index("index-NEW.js", "index-NEW.css"))

    with caplog.at_level(logging.ERROR, logger="finance_analysis.interfaces.api.app"):
        missing = app_module._check_frontend_assets_consistency(static_dir)

    assert sorted(missing) == ["/assets/index-NEW.css", "/assets/index-NEW.js"]
    assert any(
        "Frontend bundle is inconsistent" in record.getMessage()
        for record in caplog.records
    )


def test_backend_startup_check_silent_when_bundle_consistent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fastapi import app as app_module

    static_dir = tmp_path / "static"
    assets = static_dir / "assets"
    assets.mkdir(parents=True)
    (assets / "index-abc.js").write_text("// js", encoding="utf-8")
    (assets / "index-abc.css").write_text("/* css */", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    with caplog.at_level(logging.ERROR, logger="finance_analysis.interfaces.api.app"):
        missing = app_module._check_frontend_assets_consistency(static_dir)

    assert missing == []
    assert not any(
        "Frontend bundle is inconsistent" in record.getMessage()
        for record in caplog.records
    )


def test_missing_asset_returns_safe_404_content_types(tmp_path: Path) -> None:
    from finance_analysis.interfaces.api.app import create_app

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "index-abc.js").write_text("// ok", encoding="utf-8")
    (assets_dir / "index-abc.css").write_text("/* ok */", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    client = TestClient(create_app(static_dir=static_dir))

    js_response = client.get("/assets/index-missing.js")
    css_response = client.get("/assets/index-missing.css")
    html_response = client.get("/assets/%3Cscript%3Ealert(1)%3C/script%3E.html")

    assert js_response.status_code == 404
    assert js_response.text == "asset not found"
    assert js_response.headers["content-type"].startswith("text/javascript")

    assert css_response.status_code == 404
    assert css_response.text == "asset not found"
    assert css_response.headers["content-type"].startswith("text/css")

    assert html_response.status_code == 404
    assert html_response.text == "asset not found"
    assert html_response.headers["content-type"].startswith("text/plain")


def test_existing_asset_is_served_from_explicit_assets_route(tmp_path: Path) -> None:
    from finance_analysis.interfaces.api.app import create_app

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    js_file = assets_dir / "index-abc.js"
    css_file = assets_dir / "index-abc.css"
    js_file.write_text("console.log('ok')", encoding="utf-8")
    css_file.write_text("body{color:#fff}", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    client = TestClient(create_app(static_dir=static_dir))

    js_response = client.get("/assets/index-abc.js")
    css_response = client.get("/assets/index-abc.css")

    assert js_response.status_code == 200
    assert js_response.text == "console.log('ok')"
    assert js_response.headers["content-type"].startswith("text/javascript")

    assert css_response.status_code == 200
    assert css_response.text == "body{color:#fff}"
    assert css_response.headers["content-type"].startswith("text/css")


def test_existing_asset_supports_head_and_conditional_requests(tmp_path: Path) -> None:
    from finance_analysis.interfaces.api.app import create_app

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    js_file = assets_dir / "index-abc.js"
    js_file.write_text("console.log('ok')", encoding="utf-8")
    (assets_dir / "index-abc.css").write_text("body{color:#fff}", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))

    client = TestClient(create_app(static_dir=static_dir))

    get_response = client.get("/assets/index-abc.js")
    etag = get_response.headers["etag"]

    head_response = client.head("/assets/index-abc.js")
    cached_response = client.get(
        "/assets/index-abc.js",
        headers={"if-none-match": etag},
    )

    assert get_response.status_code == 200
    assert head_response.status_code == 200
    assert head_response.content == b""
    assert head_response.headers["etag"] == etag
    assert head_response.headers["content-type"].startswith("text/javascript")

    assert cached_response.status_code == 304
    assert cached_response.content == b""
    assert cached_response.headers["etag"] == etag


@pytest.mark.parametrize(
    "request_path",
    [
        "/assets/..%5C..%5Csecret.txt",
        "/assets/C:%5Csecret.txt",
        "/assets/%5Cwindows%5Csystem32%5Cconfig",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/assets/%2500.js",
    ],
)
def test_asset_traversal_attempts_are_rejected(
    tmp_path: Path,
    request_path: str,
) -> None:
    from finance_analysis.interfaces.api.app import create_app

    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "index-abc.js").write_text("// ok", encoding="utf-8")
    (assets_dir / "index-abc.css").write_text("/* ok */", encoding="utf-8")
    _write_index(static_dir, _vite_index("index-abc.js", "index-abc.css"))
    outside_secret = tmp_path / "secret.txt"
    outside_secret.write_text("top secret", encoding="utf-8")

    client = TestClient(create_app(static_dir=static_dir))
    response = client.get(request_path)

    assert response.status_code == 404
    assert response.text == "not found"
    assert "top secret" not in response.text
