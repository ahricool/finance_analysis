# Signal Center retry status repair

Production validation after deploying main `9622541` found that a US final CLI call timed out at 180 seconds.
The five screening buckets and frozen input were correctly preserved. However, while a manual retry's task record
was `processing`, `signal_center_run.status` remained `failed`, so the page displayed failure during an active retry.

The service now writes `pending` and clears the previous signal error after acquiring its existing market/day lock,
before resuming screening or final synthesis. The previous failed attempt remains in task history. It does not
change frozen candidates, bucket membership, successful screening results, prompts, or the completed/skipped guard.
This change fixes state reporting; it does not change provider timeouts or claim to resolve external CLI latency.

## Three review passes

1. State transitions: failed → pending precedes the slow call; a subsequent exception again writes failed.
   GET responses and the existing page can immediately report analysis in progress without frontend changes.
2. Historical evidence: retry uses the original snapshot and saved screening batches; assertions inspect these
   values during the resumed final call. Failed-bucket recovery also verifies pending state before each call.
3. Idempotence and scope: completed/skipped and busy-lock paths retain their early exits. Repeated final failures
   neither rerun successful buckets nor lose their evidence. No schema, task schedule, or production config changes.

Validation: `tests/signal_center` 45 passed / 4 skipped (isolated PostgreSQL tests not enabled for this code-only repair),
repository flake8 and diff checks passed. The repair is submitted separately for review; it is not deployed in-place.

Production follow-up: CN completed and passed bucket/output/immutability checks. US kept all five completed buckets,
but final calls timed out twice at180s and once with a one-off360s budget. A minimal CLI probe also timed out at30s.
No persistent timeout configuration was changed. US final output remains unresolved; this PR does not claim to fix
CLI availability. The production row remains failed rather than fabricating NO_TRADE.
