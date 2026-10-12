# celery_app.py - Fixed Version
import os
from celery import Celery
from celery.signals import worker_ready, task_postrun
import logging
import redis

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Get Redis URL from environment or use default
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Create Celery app
celery_app = Celery(
    'fayda_bot',
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=['tasks']
)

# Configure Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Africa/Addis_Ababa',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_compression='gzip',
    result_compression='gzip',
)


@worker_ready.connect
def at_start(sender, **k):
    logging.info("🚀 Celery worker is ready and waiting for tasks...")


# Clean up task_to_job_map entries when task completes
@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, **kwargs):
    try:
        r = redis.from_url(REDIS_URL)
        r.hdel("task_to_job_map", task_id)
    except Exception:
        pass


if __name__ == '__main__':
    celery_app.start()
