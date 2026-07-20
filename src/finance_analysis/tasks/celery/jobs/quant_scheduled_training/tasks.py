from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS
from finance_analysis.tasks.lifecycle import track_task


def _dispatch_training(model_run_id: int | None, expected_market: str) -> dict:
    if model_run_id is None:
        raise ValueError(
            f"Scheduled {expected_market} training requires an explicit {expected_market} model_run_id; "
            "create it through the admin API"
        )
    from finance_analysis.database.repositories.quant import QuantRepository

    run = QuantRepository().get_model_run(model_run_id)
    if run is None:
        raise ValueError(f"Model run {model_run_id} not found")
    if run.market != expected_market:
        raise ValueError(
            f"Model run {model_run_id} belongs to market={run.market}, expected market={expected_market}"
        )
    result = celery_app.send_task(
        "quant.model.train",
        kwargs={"model_run_id": model_run_id},
        queue=QUEUE_ANALYSIS,
    )
    return {
        "model_run_id": model_run_id,
        "dispatch_task_id": result.id,
        "status": "queued",
        "market": expected_market,
    }


@celery_app.task(name="scheduled.quant_model_training_us")
@track_task(
    task_type="scheduled_quant_training_us",
    task_name="美股量化模型训练",
    source="celery_schedule",
    record_result=True,
)
def quant_model_training_us(model_run_id: int | None = None, **_) -> dict:
    return _dispatch_training(model_run_id, "US")


@celery_app.task(name="scheduled.quant_model_training_cn")
@track_task(
    task_type="scheduled_quant_training_cn",
    task_name="A股量化模型训练",
    source="celery_schedule",
    record_result=True,
)
def quant_model_training_cn(model_run_id: int | None = None, **_) -> dict:
    return _dispatch_training(model_run_id, "CN")
