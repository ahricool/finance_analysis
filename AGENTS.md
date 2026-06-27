# Repository Guidelines

## Project Structure & Module Organization

The Python application lives in the `src/finance_analysis/` package (src layout). Do **not** recreate legacy root-level `api/`, `bot/`, `data_provider/`, or global `services/` directories.

- `src/finance_analysis/`: formal Python application package
- `src/finance_analysis/interfaces/api/`: FastAPI app, middleware, routes, and API schemas
- `src/finance_analysis/interfaces/bot/`: bot commands, dispatcher, and platform adapters
- `src/finance_analysis/integrations/market_data/`: market data providers and fetcher management
- `src/finance_analysis/database/`: SQLAlchemy models (`database/models/`), repositories (`database/repositories/`), and session management
- `src/finance_analysis/tasks/`: APScheduler, Celery, and background jobs
- `src/finance_analysis/analysis/`: stock analysis services and pipeline
- `src/finance_analysis/notification/`: notification routing and delivery channels
- `src/finance_analysis/reporting/`: report rendering and localization
- `src/finance_analysis/llm/`: shared LLM client and model management
- `src/finance_analysis/core/paths.py`: unified project-root and `DATA_DIR` runtime path helpers (`PROJECT_ROOT`, `STATIC_DIR`, `WEB_DIR`, `get_data_dir()`, `get_log_dir()`, `ensure_data_directories()`, etc.)
- `strategies/`: YAML strategy definitions; update `strategies/README.md` for behavior changes
- `alembic/`: database migrations; keep schema changes here
- `web/`: Vue 3 + TypeScript frontend, Vitest tests, and Playwright smoke tests
- `static/`: built WebUI assets served by the nginx frontend image
- `templates/`: Jinja2 report templates
- `tests/`: backend pytest suite; network/live tests are separate from offline tests

**Placement rules**

- Put domain services inside their owning module (e.g. analysis logic under `analysis/`, not a global `services/` tree).
- ORM models belong in `database/models/`.
- Repositories belong in `database/repositories/`.

## Build, Test, and Development Commands

- `uv sync`: install backend dependencies from `pyproject.toml` and `uv.lock`.
- `uv run python main.py`: run the backend locally.
- `uv run finance-analysis`: same entrypoint via the installed CLI.
- `docker compose -f docker-compose.dev.yml up --build`: start PostgreSQL, Redis, and the app.
- `./scripts/ci_gate.sh`: run backend syntax, critical flake8, deterministic, and offline pytest checks.
- `cd web && pnpm run dev`: start Vite.
- `cd web && pnpm run build && pnpm run lint && pnpm run test`: run frontend build, lint, and unit tests.
- `cd web && pnpm run test:smoke`: run Playwright smoke tests.

## Coding Style & Naming Conventions

Use 4-space indentation for Python and keep lines at or below 120 characters. `black` and `isort` settings are in `pyproject.toml`. Python modules and functions use `snake_case`; classes use `PascalCase`; constants and environment variables use `UPPER_SNAKE_CASE`.

Frontend code uses TypeScript, Vue single-file components, ESLint, and Tailwind. Prefer existing component and styling patterns in `web/src/` before introducing new conventions.

## Testing Guidelines

Backend tests use pytest and should be named `tests/test_*.py`. Keep tests deterministic and offline by default; mark network-dependent checks with `network`. Add focused tests when changing service behavior, API contracts, storage, strategies, or frontend flows.

Path-related tests should use `finance_analysis.core.paths` constants or explicit temporary directories — do not mock module `__file__` to fake the pre-refactor layout.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries such as `fix jwt error`, `Update background`, and `add redis dependency (#64)`. Keep subjects concise and describe the user-visible change. Use `#patch`, `#minor`, or `#major` on main only when intentionally triggering auto-tagging.

Pull requests should include a clear description, linked issue when applicable, test results, and screenshots for UI changes. Note migration, configuration, or deployment impact.

## Security & Configuration Tips

Copy `.env.example` to `.env` for local setup and never commit real secrets. Treat `.github/workflows/`, `.github/scripts/`, Docker publishing config, API keys, database URLs, and notification tokens as sensitive review areas.

Default `.env` path is `<project-root>/.env`; override with `ENV_FILE` for all config loaders (`load_env()`, `setup_env()`, `ConfigManager`).

## Cursor Cloud specific instructions

Standard commands live in "Build, Test, and Development Commands" above. The notes below are non-obvious caveats for running this stack natively in the Cursor Cloud VM (no Docker; PostgreSQL 16 and Redis 7 are installed and run directly). <!-- pragma: allowlist secret -->

### Services
- PostgreSQL and Redis are installed via `apt` and are **not** managed by systemd. Start them manually if not already running: `sudo pg_ctlcluster 16 main start` and `sudo redis-server /etc/redis/redis.conf --daemonize yes`. A local Postgres role + database are provisioned matching the injected `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` secret values, plus a second database (same name with a `_test` suffix) for the pytest suite. <!-- pragma: allowlist secret -->
- Backend (FastAPI/uvicorn): `uv run python main.py` → API on `:8000` (`/docs`). Frontend (Vite): `cd web && pnpm run dev` → `:5173`, proxies `/api` and `/docs` to the backend on port 8000.

### Injected DB/Redis URLs are docker-compose templates (must override for native runs)
The Cloud Agent injects `DATABASE_URL` and `REDIS_URL` as environment secrets, but their values are docker-compose templates: they contain literal, unexpanded `${POSTGRES_PORT}` / `${REDIS_PORT}` and the in-compose hostnames (`postgres` / `redis`). `load_dotenv` uses `override=False`, so these env vars win over `.env` and break a native run. When running the backend or backend tests natively, export working local URLs in the same command before `uv run python main.py`: a `postgresql+psycopg2://` URL built from the `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` secrets pointing at `localhost:5432`, and `REDIS_URL=redis://localhost:6379/0`. <!-- pragma: allowlist secret -->

### Fresh-database migration gotcha
`alembic upgrade head` (which the app runs automatically on first DB use via `DatabaseManager` → `bootstrap_database`) **fails on a brand-new database** at revision `0003`, because the collapsed baseline `0001` does `Base.metadata.create_all()` from the *current* ORM (which no longer contains the `backtest_summaries` table removed in `0011`), yet `0003` tries to `ALTER TABLE backtest_summaries`. Bootstrap a fresh DB without code changes by running the baseline and then stamping head:
`uv run alembic upgrade 0001_baseline` then `uv run alembic stamp head`.
The baseline already creates the full final schema (all `uid` columns, `task`, `finance_events`, etc.), so stamping to head is correct and the app's subsequent automatic `alembic upgrade head` becomes a harmless no-op. The migrated Postgres data persists in the VM snapshot, so this is normally a one-time step. <!-- pragma: allowlist secret -->

### Auth / default admin
The app seeds a built-in admin on first DB init: username `Ahri`, email `whoreahri@gmail.com`, with **no password** (set on first login). Login is a two-step flow: lookup email → set password (min 6 chars) → log in. A dev password was already set during setup, so just log in with it.

### Backend test caveat with injected LLM secrets
When the injected `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` secrets are present, `tests/test_agent_pipeline.py::TestAgentConstructionChain::test_llm_adapter_reports_missing_configuration_without_generic_none_error` fails (it asserts an unconfigured-LLM error path). Run the backend suite with those three vars unset to get a clean pass, e.g. prefix with `env -u LLM_MODEL -u LLM_API_KEY -u LLM_BASE_URL`.
