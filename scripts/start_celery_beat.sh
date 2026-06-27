#!/bin/sh
set -eu

schedule_file="${CELERY_BEAT_SCHEDULE_FILE:-/tmp/celerybeat-schedule}"

# Beat pickles schedule objects into this file. Rebuild it from the current
# application config on every container start so deployments cannot load
# objects from an older code layout.
rm -f \
  "${schedule_file}" \
  "${schedule_file}.db" \
  "${schedule_file}.dat" \
  "${schedule_file}.dir" \
  "${schedule_file}.bak"

exec celery \
  -A finance_analysis.tasks.celery.app:celery_app \
  beat \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --schedule="${schedule_file}" \
  "$@"
