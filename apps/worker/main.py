"""
ProspectOS AI Worker
Polls Redis job queues and dispatches to appropriate job handlers.
"""
import asyncio
import signal
import structlog
import sentry_sdk

from config import settings
from jobs.research import ResearchJob
from jobs.scoring import ScoringJob
from jobs.comment_draft import CommentDraftJob
from jobs.outreach_draft import OutreachDraftJob
from jobs.normalize import NormalizeJob
from jobs.intent import IntentJob
from jobs import source_scan as source_scan_module

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env)

log = structlog.get_logger()

JOB_HANDLERS = {
    "lead.research": ResearchJob,
    "lead.score": ScoringJob,
    "comment.generate": CommentDraftJob,
    "outreach.generate": OutreachDraftJob,
    "post.normalize": NormalizeJob,
    "post.intent": IntentJob,
    # source.scan uses a function-based handler (not a class)
    "source.scan": None,
}


async def process_job(redis_client, db_pool, job_type: str, payload: dict) -> None:
    # source.scan uses a function-based handler that needs a raw DB connection
    if job_type == "source.scan":
        async with db_pool.acquire() as conn:
            try:
                await source_scan_module.handle(payload, conn)
            except Exception as exc:
                log.error("job_failed", job_type=job_type, error=str(exc))
                sentry_sdk.capture_exception(exc)
        return

    handler_cls = JOB_HANDLERS.get(job_type)
    if not handler_cls:
        log.warning("unknown_job_type", job_type=job_type)
        return

    handler = handler_cls(redis_client=redis_client, db_pool=db_pool)
    try:
        await handler.run(payload)
    except Exception as exc:
        log.error("job_failed", job_type=job_type, payload=payload, error=str(exc))
        sentry_sdk.capture_exception(exc)


async def worker_loop(redis_client, db_pool) -> None:
    queue_key = "prospectOS:jobs"
    log.info("worker_started", queues=[queue_key], concurrency=settings.worker_concurrency)

    semaphore = asyncio.Semaphore(settings.worker_concurrency)

    async def bounded_process(job_type, payload):
        async with semaphore:
            await process_job(redis_client, db_pool, job_type, payload)

    while True:
        try:
            item = await redis_client.brpop(queue_key, timeout=int(settings.worker_queue_poll_interval))
            if item is None:
                continue

            import json
            _, raw = item
            job = json.loads(raw)
            job_type = job.get("type", "")
            payload = job.get("payload", {})

            log.info("job_dequeued", job_type=job_type, lead_id=payload.get("lead_id"))
            asyncio.create_task(bounded_process(job_type, payload))

        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("worker_loop_error", error=str(exc))
            await asyncio.sleep(1)


async def main():
    import redis.asyncio as aioredis
    import asyncpg

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    db_pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)

    loop = asyncio.get_event_loop()
    stop = asyncio.Event()

    def _signal_handler():
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    worker_task = asyncio.create_task(worker_loop(redis_client, db_pool))
    await stop.wait()
    worker_task.cancel()
    await asyncio.gather(worker_task, return_exceptions=True)

    await redis_client.aclose()
    await db_pool.close()
    log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
