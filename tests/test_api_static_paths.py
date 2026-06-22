# -*- coding: utf-8 -*-
"""Tests for FastAPI/frontend serving boundaries."""

from __future__ import annotations

from fastapi.testclient import TestClient

from finance_analysis.interfaces.api.app import create_app


def test_create_app_does_not_serve_frontend_root() -> None:
    client = TestClient(create_app())
    response = client.get("/")

    assert response.status_code == 404


def test_create_app_does_not_serve_frontend_assets() -> None:
    client = TestClient(create_app())
    response = client.get("/assets/index-abc.js")

    assert response.status_code == 404


def test_api_routes_remain_available() -> None:
    client = TestClient(create_app())
    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
