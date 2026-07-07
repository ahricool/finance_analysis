from datetime import date

from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.lifecycle import track_task


@celery_app.task(name="quant.dataset.build")
@track_task(task_type="quant_dataset", task_name="构建量化数据集", source="celery_manual", uid_getter=lambda owner_uid=None, **_: owner_uid, record_result=True)
def build_quant_dataset(market: str, universe: str, date_from: str, date_to: str, owner_uid: int | None = None, **_) -> dict:
    del owner_uid
    snapshot=QlibDatasetExporter().export(market,universe,date.fromisoformat(date_from),date.fromisoformat(date_to))
    return {"dataset_snapshot_id":snapshot.id,"dataset_key":snapshot.dataset_key,"status":snapshot.status,"row_count":snapshot.row_count,"symbol_count":snapshot.symbol_count}
