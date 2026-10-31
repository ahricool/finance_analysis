"""Conservative reclamation of task-owned inputs and reviewable legacy inventory."""
from __future__ import annotations

from datetime import timedelta
from sqlalchemy import select

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.quant import QuantDatasetSnapshot, ModelRun, QuantExecution
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.datasets.transient import PredictionInputs


def cleanup_inputs(repository=None, inputs=None, *, dry_run=True):
    repo = repository or QuantRepository()
    manager = inputs or PredictionInputs()
    cutoff = utc_now() - timedelta(hours=24)
    candidates = []
    abandoned = []
    # Fence abandoned executions before reclaiming files. A worker heartbeat protects
    # long-running computation; the input lock protects readers during reclamation.
    with repo.db.session_scope() as session:
        for row in session.scalars(select(QuantExecution).where(
                QuantExecution.status.in_(['preparing', 'predicting']), QuantExecution.created_at < cutoff)
                .with_for_update(skip_locked=True)):
            root = manager.store.path(f'temporary/{row.id}')
            heartbeat = root / '.lease'
            if heartbeat.exists() and heartbeat.stat().st_mtime >= cutoff.timestamp():
                continue
            abandoned.append({"execution_id": row.id, "lifecycle_task_id": row.task_id, "market": row.market})
            if not dry_run:
                row.status = 'failed'
                row.error = '任务超过24小时无心跳，已终止；迟到结果不会发布'
                row.finished_at = utc_now()
                row.input_uri = row.input_uri or f'quant://temporary/{row.id}'
    if not dry_run:
        from finance_analysis.tasks.celery.jobs.quant_daily.tasks import _mark_final_status
        for context in abandoned:
            _mark_final_status(context, error=RuntimeError("任务超过24小时无心跳，已终止"))
    with repo.db.get_session() as session:
        for row in session.scalars(select(QuantExecution).where(QuantExecution.input_uri.is_not(None))):
            terminal = row.status in {'complete', 'failed'}
            if terminal:
                candidates.append((row.id, row.input_uri))
    removed = []
    for execution_id, uri in candidates:
        if dry_run or manager.remove(uri):
            removed.append(execution_id)
            if not dry_run:
                with repo.db.session_scope() as session:
                    row = session.get(QuantExecution, execution_id, with_for_update=True)
                    if row and row.status in {'complete', 'failed'}:
                        row.input_uri = None
    # Unknown directories are not deleted merely because they are old.
    return {'dry_run': dry_run, 'execution_ids': removed,
            'abandoned_execution_ids': [item['execution_id'] for item in abandoned]}


def legacy_inventory(repository=None):
    """Review only. Length alone never proves that a legacy input is disposable."""
    repo = repository or QuantRepository()
    with repo.db.get_session() as session:
        referenced = set(session.scalars(select(ModelRun.dataset_snapshot_id).where(ModelRun.dataset_snapshot_id.is_not(None))))
        return [{'id': row.id, 'market': row.market, 'date_from': str(row.date_from), 'date_to': str(row.date_to),
                 'referenced_by_model': row.id in referenced, 'status': row.status,
                 'classification': 'training_reference' if row.id in referenced else 'requires_review'}
                for row in session.scalars(select(QuantDatasetSnapshot).order_by(QuantDatasetSnapshot.id))]
