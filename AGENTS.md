# Repository Guidelines

## Project Structure & Module Organization

- `api/`: FastAPI app, middleware, dependencies, and versioned API routes.
- `src/`: services, analysis pipeline, configuration, storage, scheduling, and reports.
- `data_provider/`: market data adapters for AkShare, Tushare, yfinance, Longbridge, and related sources.
- `bot/`: command handling and bot integrations.
- `strategies/`: YAML strategy definitions; update `strategies/README.md` for behavior changes.
- `alembic/`: database migrations; keep schema changes here.
- `web/`: Vue 3 + TypeScript frontend, Vitest tests, and Playwright smoke tests.
- `tests/`: backend pytest suite; network/live tests are separate from offline tests.

## Build, Test, and Development Commands

- `uv sync`: install backend dependencies from `pyproject.toml` and `uv.lock`.
- `uv run python main.py`: run the backend locally.
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

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries such as `fix jwt error`, `Update background`, and `add redis dependency (#64)`. Keep subjects concise and describe the user-visible change. Use `#patch`, `#minor`, or `#major` on main only when intentionally triggering auto-tagging.

Pull requests should include a clear description, linked issue when applicable, test results, and screenshots for UI changes. Note migration, configuration, or deployment impact.

## Security & Configuration Tips

Copy `.env.example` to `.env` for local setup and never commit real secrets. Treat `.github/workflows/`, `.github/scripts/`, Docker publishing config, API keys, database URLs, and notification tokens as sensitive review areas.
