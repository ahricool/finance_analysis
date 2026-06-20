#!/usr/bin/env python3
"""Runtime path smoke checks for Docker images."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    from finance_analysis.core.paths import (
        PROJECT_ROOT,
        STATIC_DIR,
        STRATEGIES_DIR,
        TEMPLATES_DIR,
        get_reports_dir,
    )
    from finance_analysis.interfaces.api.app import create_app
    from finance_analysis.reporting.template_renderer import _resolve_templates_dir

    print("PROJECT_ROOT =", PROJECT_ROOT)
    print("STATIC_DIR =", STATIC_DIR)
    print("TEMPLATES_DIR =", TEMPLATES_DIR)
    print("STRATEGIES_DIR =", STRATEGIES_DIR)

    assert (PROJECT_ROOT / "pyproject.toml").is_file(), PROJECT_ROOT
    assert STATIC_DIR.name == "static", STATIC_DIR
    assert (STATIC_DIR / "index.html").is_file(), STATIC_DIR

    templates = _resolve_templates_dir()
    print("templates =", templates)
    assert templates.is_dir(), templates
    assert (templates / "report_markdown.j2").is_file(), templates

    assert STRATEGIES_DIR.is_dir(), STRATEGIES_DIR

    app = create_app()
    print("routes =", len(app.routes))
    assert len(app.routes) > 0

    reports_dir = get_reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    smoke_file = reports_dir / "smoke.txt"
    smoke_file.write_text("ok", encoding="utf-8")
    assert smoke_file.read_text(encoding="utf-8") == "ok"
    smoke_file.unlink(missing_ok=True)

    print("Docker runtime paths OK")
    return 0


if __name__ == "__main__":
    if os.getenv("REPORTS_DIR"):
        sys.exit(main())
    os.environ["REPORTS_DIR"] = "/tmp/reports"
    sys.exit(main())
