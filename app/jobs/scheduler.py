# app/jobs/scheduler.py
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

# Setup logging for the scheduler process
logger = logging.getLogger(__name__)

# ✅ Configure the scheduler to use an AsyncIO executor
# This ensures that our 'async def' job functions are properly awaited
# in the background thread without blocking or crashing the event loop.
executors = {
    "default": AsyncIOExecutor()
}

# The application lifespan already owns an asyncio event loop. Using the
# asyncio scheduler ensures coroutine jobs are awaited on that loop.
scheduler = AsyncIOScheduler(timezone="UTC", executors=executors)


# ✅ Job lifecycle listeners — surface execution success/failure in logs
# so silent failures in background jobs no longer hide behind APScheduler defaults.
def _on_job_executed(event):
    logger.info(f"✅ Job completed: {event.job_id}")


def _on_job_error(event):
    logger.error(
        f"❌ Job FAILED: {event.job_id} — exception={event.exception!r}, traceback={event.traceback}",
    )


scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)


def _register_job(job_func, trigger, job_id, name):
    """
    Register a single job independently. If the import or registration
    of one job fails, it does NOT prevent the other jobs from starting.
    """
    try:
        scheduler.add_job(
            job_func,
            trigger=trigger,
            id=job_id,
            name=name,
            replace_existing=True,
            max_instances=1,          # ✅ Prevents pile-up if a run overruns its interval
            misfire_grace_time=3600,  # Allow job to run if missed by up to 1 hour
        )
        logger.info(f"✅ Registered job: {name} ({job_id})")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to register job '{name}' ({job_id}): {e}", exc_info=True)
        return False


def start_scheduler():
    """
    Starts the background scheduler.
    Only starts if ENABLE_SCHEDULER is set to 'true' in the environment.
    """
    # 1. Environment Guard: Prevent multi-pod execution conflicts
    # (Redis distributed locks inside the jobs themselves are a second layer of defense)
    enable_scheduler = os.getenv("ENABLE_SCHEDULER", "false").lower() == "true"

    if not enable_scheduler:
        logger.info("Scheduler disabled on this instance. Skipping startup.")
        return

    logger.info("Starting background scheduler with AsyncIO executor...")

    # 2. ✅ Independent imports — one broken module no longer blocks the others.
    #    Each is imported lazily and registered in isolation.
    jobs_to_register = []

    try:
        from app.jobs.subscription_jobs import run_subscription_lifecycle
        jobs_to_register.append((
            run_subscription_lifecycle,
            CronTrigger(hour=0, minute=0),
            "subscription_lifecycle",
            "Daily subscription lifecycle check",
        ))
    except Exception as e:
        logger.error(f"❌ Could not import subscription_jobs: {e}", exc_info=True)

    try:
        from app.jobs.booking_jobs import run_booking_auto_archive
        jobs_to_register.append((
            run_booking_auto_archive,
            CronTrigger(hour=1, minute=0),
            "booking_auto_archive",
            "Daily booking auto-archive",
        ))
    except Exception as e:
        logger.error(f"❌ Could not import booking_jobs: {e}", exc_info=True)

    try:
        from app.jobs.daily_commission import run_daily_commission_routine
        jobs_to_register.append((
            run_daily_commission_routine,
            CronTrigger(hour=21, minute=5),  # ✅ 00:05H EAT = 21:05H UTC
            "daily_commission",
            "Daily commission statements (00:05H EAT)",
        ))
    except Exception as e:
        logger.error(f"❌ Could not import daily_commission: {e}", exc_info=True)

    # ✅ FREQUENT AUTOSTART: runs every 5 minutes to start signed trips at pickup time
    try:
        from app.services.daily_scheduler import DailySchedulerService
        jobs_to_register.append((
            DailySchedulerService.run_frequent_autostart,
            IntervalTrigger(minutes=5),
            "frequent_autostart",
            "Auto-start signed trips at pickup time (every 5 min)",
        ))
    except Exception as e:
        logger.error(f"❌ Could not import DailySchedulerService: {e}", exc_info=True)

    # 3. Register each job independently
    for func, trigger, job_id, name in jobs_to_register:
        _register_job(func, trigger, job_id, name)

    # 4. Start the scheduler (only if at least one job registered successfully)
    if not jobs_to_register:
        logger.warning("⚠️ No jobs registered — scheduler will not start.")
        return

    try:
        scheduler.start()
        logger.info(f"✅ Scheduler started with {len(jobs_to_register)} job(s).")
    except Exception as e:
        logger.error(f"❌ Failed to start scheduler: {e}", exc_info=True)


def stop_scheduler():
    """
    Safely shuts down the scheduler only if it is currently running.
    """
    if scheduler.running:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown(wait=True)  # ✅ wait=True ensures running jobs finish gracefully
    else:
        logger.info("Scheduler was not running. Skipping shutdown.")
