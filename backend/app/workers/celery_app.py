from celery import Celery

from app.core.config import get_settings
from app.core.monitoring import init_monitoring

settings = get_settings()
init_monitoring(settings)

celery_app = Celery(
    "piano",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
)
# Task modules are listed in `include` above. app/workers/tasks.py holds the daily expiry emails.
