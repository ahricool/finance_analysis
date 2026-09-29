#!/usr/bin/env python3
"""Runtime path smoke checks for Docker images."""

from __future__ import annotations

import os
import shutil
import sys
from importlib.metadata import distribution
from pathlib import Path


def main() -> int:
    from finance_analysis.core.paths import (
        PROJECT_ROOT,
        TEMPLATES_DIR,
        clear_paths_cache,
        ensure_data_directories,
        get_data_dir,
        get_log_app_dir,
        get_report_analysis_dir,
    )
    from finance_analysis.interfaces.api.app import create_app
    from finance_analysis.reporting.template_renderer import _resolve_templates_dir

    if os.getenv("DATA_DIR"):
        clear_paths_cache()

    print("PROJECT_ROOT =", PROJECT_ROOT)
    print("DATA_DIR =", get_data_dir())
    print("TEMPLATES_DIR =", TEMPLATES_DIR)

    assert (PROJECT_ROOT / "pyproject.toml").is_file(), PROJECT_ROOT

    templates = _resolve_templates_dir()
    print("templates =", templates)
    assert templates.is_dir(), templates
    assert (templates / "report_markdown.j2").is_file(), templates

    # The production streamer uses a project console script, not python main.py.
    project = distribution("finance_analysis")
    entrypoints = {ep.name: ep for ep in project.entry_points if ep.group == "console_scripts"}
    for name in ("finance-analysis", "finance-analysis-stream"):
        assert shutil.which(name), name
        assert callable(entrypoints[name].load()), name
    assert Path(sys.executable).parent == PROJECT_ROOT / ".venv" / "bin", sys.executable
    assert (PROJECT_ROOT / "alembic.ini").is_file()
    assert (PROJECT_ROOT / "alembic" / "env.py").is_file()

    ensure_data_directories()
    assert get_log_app_dir().is_dir()
    assert get_report_analysis_dir().is_dir()

    app = create_app()
    print("routes =", len(app.routes))
    assert len(app.routes) > 0

    reports_dir = get_report_analysis_dir()
    smoke_file = reports_dir / "smoke.txt"
    smoke_file.write_text("ok", encoding="utf-8")
    assert smoke_file.read_text(encoding="utf-8") == "ok"
    smoke_file.unlink(missing_ok=True)

    print("Docker runtime paths OK")
    return 0


if __name__ == "__main__":
    if os.getenv("DATA_DIR"):
        sys.exit(main())
    os.environ["DATA_DIR"] = "/tmp/finance-analysis-data"
    sys.exit(main())
