"""Avatar image, isolated persistence, migration and failure boundaries."""

from contextlib import contextmanager
from io import BytesIO
import importlib.util
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations

from finance_analysis.database.models import User, UserAvatar
from finance_analysis.database.repositories.user import UserRepository
from finance_analysis.users.avatar import InvalidAvatar, normalize_avatar


def picture(fmt="PNG", size=(90, 30)):
    output = BytesIO()
    im = Image.new("RGB", size, "red")
    im.paste("green", (30, 0, 60, 30))
    im.save(output, format=fmt)
    return output.getvalue()


@pytest.mark.parametrize("fmt,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_normalize_center_crop_and_webp(fmt, mime):
    result = Image.open(BytesIO(normalize_avatar(picture(fmt), mime)))
    assert result.size == (256, 256)
    assert result.format == "WEBP"
    r, g, b = result.convert("RGB").getpixel((128, 128))
    assert g > r and g > b
    assert not result.getexif()


def test_invalid_images():
    for data, mime in [
        (b"", "image/png"),
        (picture(), "image/jpeg"),
        (picture()[:40], "image/png"),
        (picture(), "image/gif"),
    ]:
        with pytest.raises(InvalidAvatar):
            normalize_avatar(data, mime)


def test_pixel_limit_and_animation(monkeypatch):
    import finance_analysis.users.avatar as avatar

    monkeypatch.setattr(avatar, "MAX_AVATAR_PIXELS", 100)
    with pytest.raises(InvalidAvatar, match="像素"):
        normalize_avatar(picture(), "image/png")
    monkeypatch.setattr(avatar, "MAX_AVATAR_PIXELS", 16_000_000)
    out = BytesIO()
    Image.new("RGB", (10, 10), "red").save(
        out, format="WEBP", save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")], duration=100
    )
    with pytest.raises(InvalidAvatar, match="静态"):
        normalize_avatar(out.getvalue(), "image/webp")


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    User.__table__.create(engine)
    UserAvatar.__table__.create(engine)

    class Database:
        @contextmanager
        def get_session(self):
            with Session(engine, expire_on_commit=False) as session:
                yield session

        def _run_write_transaction(self, name, action):
            with Session(engine, expire_on_commit=False) as session, session.begin():
                return action(session)

    with Session(engine) as session, session.begin():
        session.add(User(id=1, username="test", email="test@example.test", role="user", extra={}))
    yield Database(), engine
    engine.dispose()


def test_binary_storage_isolated_from_user_reads_and_deleted_with_user(db):
    database, engine = db
    repo = UserRepository(database)
    blob = normalize_avatar(picture(), "image/png")
    first = repo.save_avatar(1, blob).avatar_url
    assert repo.get_avatar(1).data == blob
    assert repo.save_avatar(1, blob).avatar_url != first
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    assert repo.get_by_uid(1).id == 1
    event.remove(engine, "before_cursor_execute", capture)
    assert all("user_avatar" not in statement for statement in statements)
    assert str(UserAvatar.__table__.c.data.type.compile(dialect=postgresql.dialect())) == "BYTEA"
    assert repo.delete_avatar(1).avatar_url is None
    assert repo.get_avatar(1) is None
    assert repo.delete_avatar(1).avatar_url is None
    assert repo.save_avatar(999, blob) is None
    repo.save_avatar(1, blob)
    with Session(engine) as session, session.begin():
        session.delete(session.get(User, 1))
    assert repo.get_avatar(1) is None


def test_failed_write_rolls_back_bytes_and_url(db, monkeypatch):
    database, engine = db
    repo = UserRepository(database)
    initial = repo.save_avatar(1, b"old").avatar_url
    original = Session.flush

    def fail(session, *args, **kwargs):
        if any(isinstance(row, UserAvatar) and row.data == b"new" for row in session.dirty):
            original(session, *args, **kwargs)
            raise RuntimeError("write failed")
        return original(session, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", fail)
    with pytest.raises(RuntimeError):
        repo.save_avatar(1, b"new")
    assert repo.get_avatar(1).data == b"old"
    assert repo.get_by_uid(1).avatar_url == initial


def test_migration_imports_legacy_files_and_schema(tmp_path, monkeypatch):
    import finance_analysis.core.paths as paths

    monkeypatch.setattr(paths, "get_avatar_upload_dir", lambda: tmp_path)
    (tmp_path / "1.jpg").write_bytes(picture("JPEG"))
    path = Path(__file__).parents[1] / "alembic/versions/0071_user_avatar.py"
    spec = importlib.util.spec_from_file_location("avatar_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(
            User.__table__.insert().values(
                id=1,
                username="test",
                email="test@example.test",
                role="user",
                avatar_url="/api/v1/auth/avatar/1.jpg?v=1",
            )
        )
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        assert {c["name"] for c in inspect(conn).get_columns("user_avatar")} == set(UserAvatar.__table__.c.keys())
        blob = conn.execute(select(UserAvatar.data)).scalar_one()
        assert Image.open(BytesIO(blob)).size == (256, 256)
        assert conn.execute(select(User.avatar_url)).scalar_one().startswith("/api/v1/auth/avatar/1.webp?v=")
        migration.import_legacy_avatars(conn)
        assert len(conn.execute(select(UserAvatar.user_id)).all()) == 1
        migration.downgrade()
        assert "user_avatar" not in inspect(conn).get_table_names()
        assert conn.execute(select(User.avatar_url)).scalar_one() is None
    engine.dispose()


def test_http_avatar_routes_return_binary_and_enforce_ownership(monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from finance_analysis.interfaces.api.v1.endpoints import auth as endpoint

    blob = normalize_avatar(picture(), "image/png")
    monkeypatch.setattr(
        endpoint,
        "UserRepository",
        lambda: SimpleNamespace(get_avatar=lambda uid: SimpleNamespace(data=blob, version="v1")),
    )
    app = FastAPI()

    @app.middleware("http")
    async def session(request: Request, call_next):
        request.state.uid = 1
        return await call_next(request)

    app.include_router(endpoint.router, prefix="/api/v1/auth")
    with TestClient(app) as client:
        for ext in ("webp", "jpg"):
            response = client.get(f"/api/v1/auth/avatar/1.{ext}")
            assert response.status_code == 200
            assert response.content == blob
            assert response.headers["content-type"] == "image/webp"
            cached = client.get(f"/api/v1/auth/avatar/1.{ext}", headers={"If-None-Match": response.headers["etag"]})
            assert cached.status_code == 304
            assert cached.content == b""
        assert client.get("/api/v1/auth/avatar/2.webp", headers={"If-None-Match": "*"}).status_code == 403


def test_exif_orientation_transparency_and_metadata():
    output = BytesIO()
    source = Image.new("RGB", (256, 256), "red")
    source.paste("blue", (0, 0, 128, 256))
    exif = Image.Exif()
    exif[274] = 3  # 180 degrees
    exif[315] = "private author"
    source.save(output, format="JPEG", exif=exif)
    result = Image.open(BytesIO(normalize_avatar(output.getvalue(), "image/jpeg")))
    assert result.getpixel((240, 128))[2] > 200
    assert not result.getexif()
    transparent = BytesIO()
    Image.new("RGBA", (24, 24), (255, 0, 0, 0)).save(transparent, format="PNG")
    result = Image.open(BytesIO(normalize_avatar(transparent.getvalue(), "image/png")))
    assert result.getpixel((128, 128))[3] == 0
