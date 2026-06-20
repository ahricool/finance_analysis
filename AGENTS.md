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
- `src/finance_analysis/core/paths.py`: unified project-root path helpers (`PROJECT_ROOT`, `STATIC_DIR`, `WEB_DIR`, etc.)
- `strategies/`: YAML strategy definitions; update `strategies/README.md` for behavior changes
- `alembic/`: database migrations; keep schema changes here
- `web/`: Vue 3 + TypeScript frontend, Vitest tests, and Playwright smoke tests
- `static/`: built WebUI assets served by the backend
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
