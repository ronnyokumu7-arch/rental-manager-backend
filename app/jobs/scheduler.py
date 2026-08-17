# app/jobs/scheduler.py
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.asyncio import AsyncIOExecutor

# Setup logging for the scheduler process
logger = logging.getLogger(__name__)

# ✅ Configure the scheduler to use an AsyncIO executor
# This ensures that our 'async def' job functions are properly awaited 
# in the background thread without blocking or crashing the event loop.
executors = {
    "default": AsyncIOExecutor()
}

# The application lifespan already owns an asyncio event loop.  Using the
# asyncio scheduler ensures coroutine jobs are awaited on that loop.
scheduler = AsyncIOScheduler(timezone="UTC", executors=executors)


def start_scheduler():
    """
    Starts the background scheduler. 
    Only starts if ENABLE_SCHEDULER is set to 'true' in the environment.
    """
    # 1. Environment Guard: Prevent multi-pod execution conflicts
    # (Note: We also have Redis distributed locks inside the jobs themselves as a second layer of defense)
    enable_scheduler = os.getenv("ENABLE_SCHEDULER", "false").lower() == "true"
    
    if not enable_scheduler:
        logger.info("Scheduler disabled on this instance. Skipping startup.")
        return

    logger.info("Starting background scheduler with AsyncIO executor...")

    # 2. Deferred imports to avoid circular dependencies
    from app.jobs.subscription_jobs import run_subscription_lifecycle
    from app.jobs.booking_jobs import run_booking_auto_archive
    from app.jobs.daily_commission import run_daily_commission_routine

    # 3. Registration with error handling
    try:
        scheduler.add_job(
            run_subscription_lifecycle,
            trigger=CronTrigger(hour=0, minute=0),  # Runs daily at midnight UTC
            id="subscription_lifecycle",
            name="Daily subscription lifecycle check",
            replace_existing=True,
            misfire_grace_time=3600,  # Allow job to run if missed by up to 1 hour
        )

        scheduler.add_job(
            run_booking_auto_archive,
            trigger=CronTrigger(hour=1, minute=0),  # Runs daily at 1:00 AM UTC
            id="booking_auto_archive",
            name="Daily booking auto-archive",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # ✅ COMMISSION STATEMENTS: 00:05H EAT = 21:05H UTC
        scheduler.add_job(
            run_daily_commission_routine,
            trigger=CronTrigger(hour=21, minute=5),
            id="daily_commission",
            name="Daily commission statements (00:05H EAT)",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        scheduler.start()
        logger.info("Scheduler started successfully.")
        
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}", exc_info=True)


def stop_scheduler():
    """
    Safely shuts down the scheduler only if it is currently running.
    """
    if scheduler.running:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown(wait=True)  # ✅ wait=True ensures running jobs finish gracefully
    else:
        logger.info("Scheduler was not running. Skipping shutdown.")
