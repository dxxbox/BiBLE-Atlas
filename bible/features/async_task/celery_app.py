from __future__ import annotations

from celery import Celery

celery_app = Celery("bible_atlas")


def configure_celery_app(
    broker_url: str,
    result_backend: str,
    *,
    task_acks_late: bool = True,
    worker_prefetch_multiplier: int = 1,
    worker_concurrency: int = 0,
) -> None:
    """Apply runtime broker/backend settings to the Celery app (call once during startup)."""
    conf: dict = dict(
        broker_url=broker_url,
        result_backend=result_backend,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_acks_late=task_acks_late,
        worker_prefetch_multiplier=worker_prefetch_multiplier,
    )
    if worker_concurrency > 0:
        conf["worker_concurrency"] = worker_concurrency
    celery_app.conf.update(conf)

