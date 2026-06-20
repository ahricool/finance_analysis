import logging

import finance_analysis.core.frontend_assets as webui_frontend


def _create_full_static(static_dir):
    """Create static/index.html + static/assets/*.js/.css (complete build)."""
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (assets_dir / "index-abc123.js").write_text("/* js */", encoding="utf-8")
    (assets_dir / "index-abc123.css").write_text("/* css */", encoding="utf-8")
    return static_dir


def test_prepare_webui_frontend_assets_reuses_prebuilt_static_without_source(tmp_path, caplog):
    frontend_dir = tmp_path / "web"
    static_dir = _create_full_static(tmp_path / "static")

    with caplog.at_level(logging.INFO):
        assert webui_frontend.prepare_webui_frontend_assets(
            frontend_dir=frontend_dir,
            static_dir=static_dir,
        ) is True

    assert "检测到可直接复用的前端静态产物" in caplog.text
    assert "未找到前端项目，无法自动构建" not in caplog.text
    assert "未检测到 npm，无法自动构建前端" not in caplog.text
    assert "assets/ 目录不存在或无 CSS/JS 文件" not in caplog.text


def test_prepare_webui_frontend_assets_fails_without_static_or_source(tmp_path, caplog):
    frontend_dir = tmp_path / "web"
    static_dir = tmp_path / "static"

    with caplog.at_level(logging.WARNING):
        assert webui_frontend.prepare_webui_frontend_assets(
            frontend_dir=frontend_dir,
            static_dir=static_dir,
        ) is False

    assert "未找到前端项目，无法自动构建" in caplog.text


def test_prepare_webui_frontend_assets_warns_when_assets_missing(tmp_path, caplog):
    frontend_dir = tmp_path / "web"
    static_dir = tmp_path / "static"
    static_index = static_dir / "index.html"
    static_index.parent.mkdir(parents=True)
    static_index.write_text("<!doctype html>", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        result = webui_frontend.prepare_webui_frontend_assets(
            frontend_dir=frontend_dir,
            static_dir=static_dir,
        )

    assert result is True
    assert "目录不存在或无 CSS/JS 文件" in caplog.text
    assert "WebUI 将因缺少样式与脚本而显示异常" in caplog.text


def test_prepare_webui_frontend_assets_auto_build_disabled_warns_when_assets_missing(tmp_path, monkeypatch, caplog):
    frontend_dir = tmp_path / "web"
    static_dir = tmp_path / "static"
    static_index = static_dir / "index.html"
    static_index.parent.mkdir(parents=True)
    static_index.write_text("<!doctype html>", encoding="utf-8")

    monkeypatch.setenv("WEBUI_AUTO_BUILD", "false")

    with caplog.at_level(logging.WARNING):
        result = webui_frontend.prepare_webui_frontend_assets(
            frontend_dir=frontend_dir,
            static_dir=static_dir,
        )

    assert result is True
    assert "目录不存在或无 CSS/JS 文件" in caplog.text


def test_has_static_assets_returns_false_for_missing_dir(tmp_path):
    assert webui_frontend._has_static_assets(tmp_path / "nonexistent") is False


def test_has_static_assets_returns_false_for_empty_assets(tmp_path):
    (tmp_path / "assets").mkdir()
    assert webui_frontend._has_static_assets(tmp_path) is False


def test_has_static_assets_returns_true_when_js_present(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "main.js").write_text("", encoding="utf-8")
    assert webui_frontend._has_static_assets(tmp_path) is True


def test_has_static_assets_returns_true_when_css_present(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "style.css").write_text("", encoding="utf-8")
    assert webui_frontend._has_static_assets(tmp_path) is True
