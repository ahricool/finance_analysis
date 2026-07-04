from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.celery.schedule import QUEUE_ANALYSIS
from finance_analysis.tasks.lifecycle import track_task


@celery_app.task(name="scheduled.quant_model_training_us")
@track_task(
    task_type="scheduled_quant_training_us",
    task_name="美股量化模型训练",
    source="celery_schedule",
    record_result=True,
)
def quant_model_training_us(model_run_id: int | None = None, **_) -> dict:
    if model_run_id is None:
        raise ValueError("Scheduled training requires an explicit model_run_id; create it through the admin API")
    result = celery_app.send_task(
        "quant.model.train",
        kwargs={"model_run_id": model_run_id},
        queue=QUEUE_ANALYSIS,
    )
    return {"model_run_id": model_run_id, "dispatch_task_id": result.id, "status": "queued"}
