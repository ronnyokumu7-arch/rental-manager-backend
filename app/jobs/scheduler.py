import logging
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Setup logging for the scheduler process
logger = logging.getLogger(__name__)

# Scheduler instance
scheduler = BackgroundScheduler(timezone="UTC")

def start_scheduler():
    """
    Starts the background scheduler. 
    Only starts if ENABLE_SCHEDULER is set to 'true' in the environment.
    """
    
    # 1. Environment Guard: Prevent multi-pod execution conflicts
    enable_scheduler = os.getenv("ENABLE_SCHEDULER", "false").lower() == "true"
    
    if not enable_scheduler:
        logger.info("Scheduler disabled on this instance. Skipping startup.")
        return

    logger.info("Starting background scheduler...")

    # Deferred imports to avoid circular dependencies
    from app.jobs.subscription_jobs import run_subscription_lifecycle
    from app.jobs.booking_jobs import run_booking_auto_archive

    # 2. Registration with error handling
    try:
        scheduler.add_job(
            run_subscription_lifecycle,
            trigger=CronTrigger(hour=0, minute=0),
            id="subscription_lifecycle",
            name="Daily subscription lifecycle check",
            replace_existing=True,
            misfire_grace_time=3600, # Allow job to run if missed by up to 1 hour
        )

        scheduler.add_job(
            run_booking_auto_archive,
            trigger=CronTrigger(hour=1, minute=0),
            id="booking_auto_archive",
            name="Daily booking auto-archive",
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
        scheduler.shutdown()
    else:
        logger.info("Scheduler was not running. Skipping shutdown.")