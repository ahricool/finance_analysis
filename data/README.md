# Runtime data directory

All application-generated files are stored under this directory. The root path
is controlled by the `DATA_DIR` environment variable (default: `<project-root>/data`;
Docker: `/workspace/data`).

## Layout

```text
data/
├── logs/
│   ├── app/          # FastAPI / main server logs
│   ├── celery/       # Celery worker and task logs
│   ├── scheduler/    # APScheduler task logs
│   └── access/       # HTTP access logs (reserved)
├── reports/
│   ├── analysis/     # Saved analysis and market-review reports
│   ├── backtest/     # Backtest output
│   ├── exports/      # CSV / Excel / JSON exports
│   └── assets/       # Report-related images and attachments
├── uploads/          # User uploads (e.g. avatars)
├── cache/            # Application cache files
├── tmp/              # Short-lived temporary files
├── runtime/
│   ├── locks/        # Cross-process lock files
│   └── pid/          # PID files
└── backups/          # Backup archives
```

## Migrating from legacy root directories

If you previously used top-level `logs/` or `reports/` at the project root, move
them into `data/` manually (the application does **not** auto-migrate on startup):

```bash
# From the project root
mkdir -p data/logs data/reports/analysis

# Move existing logs (preserve subdirectories when present)
if [ -d logs ]; then
  rsync -a logs/ data/logs/
fi

# Move existing reports into analysis/
if [ -d reports ]; then
  rsync -a reports/ data/reports/analysis/
fi
```

Review the copied files, then remove the old directories when you are satisfied:

```bash
# Optional — only after verifying data/ contains what you need
# rm -rf logs reports
```

Set `DATA_DIR` if you keep runtime data outside the default location:

```bash
export DATA_DIR=/path/to/your/data
```
