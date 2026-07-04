from finance_analysis.quant.pipeline.service import QuantTrainingPipeline
from finance_analysis.tasks.celery.app import celery_app
from finance_analysis.tasks.lifecycle import track_task


@celery_app.task(name="quant.model.train")
@track_task(task_type="quant_training", task_name="训练量化模型", source="celery_manual", uid_getter=lambda model_run_id, owner_uid=None, **_: owner_uid, record_result=True)
def train_quant_model(model_run_id: int, owner_uid: int | None = None, **_) -> dict:
    del owner_uid
    return QuantTrainingPipeline().run(model_run_id)
