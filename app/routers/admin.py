from fastapi import APIRouter, Depends
from app.dependencies.auth import get_current_user
from app.dependencies.rbac import require_role
from app.jobs.booking_jobs import run_booking_auto_archive
from app.jobs.subscription_jobs import run_subscription_lifecycle
from app.models.users import User, UserRole

router = APIRouter(prefix="/admin", tags=["admin"])

# We define the dependency once here for cleaner code
super_admin_only = Depends(require_role([UserRole.super_admin]))

@router.post("/jobs/run-subscription-lifecycle")
def trigger_subscription_lifecycle(
    current_user: User = super_admin_only
):
    run_subscription_lifecycle()
    return {"message": "Subscription lifecycle job completed"}

@router.post("/jobs/run-booking-archive")
def trigger_booking_archive(
    current_user: User = super_admin_only
):
    run_booking_auto_archive()
    return {"message": "Booking auto-archive job completed"}