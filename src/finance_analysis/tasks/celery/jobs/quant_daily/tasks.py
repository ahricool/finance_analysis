from finance_analysis.quant.pipeline.service import QuantDailyPipeline
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.lifecycle import track_task


@celery_app.task(name="scheduled.quant_daily_pipeline_us")
@track_task(task_type="scheduled_quant_daily_us", task_name="美股量化日频流水线", source="celery_schedule", record_result=True)
def quant_daily_pipeline_us(**_) -> dict:
    return QuantDailyPipeline().run()
