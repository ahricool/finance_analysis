from datetime import date

from finance_analysis.quant.datasets.exporter import QlibDatasetExporter
from finance_analysis.quant.markets import validate_universe_for_market
from finance_analysis.quant.price_modes import DEFAULT_QUANT_PRICE_MODE
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.lifecycle import track_task


@celery_app.task(name="quant.dataset.build")
@track_task(
    task_type="quant_dataset",
    task_name="构建量化数据集",
    source="celery_manual",
    uid_getter=lambda owner_uid=None, **_: owner_uid,
    record_result=True,
)
def build_quant_dataset(
    market: str,
    date_from: str,
    date_to: str,
    universe: str | None = None,
    owner_uid: int | None = None,
    **_,
) -> dict:
    del owner_uid
    universe = validate_universe_for_market(market, universe)
    end_date = date.fromisoformat(date_to)
    snapshot = QlibDatasetExporter().export(
        market,
        universe,
        date.fromisoformat(date_from),
        end_date,
        price_mode=DEFAULT_QUANT_PRICE_MODE.value,
    )
    return {
        "dataset_snapshot_id": snapshot.id,
        "dataset_key": snapshot.dataset_key,
        "status": snapshot.status,
        "market": market.upper(),
        "universe": universe,
        "price_mode": snapshot.price_mode,
        "row_count": snapshot.row_count,
        "symbol_count": snapshot.symbol_count,
    }
