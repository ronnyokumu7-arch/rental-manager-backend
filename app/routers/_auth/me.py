from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.dependencies.subscription import get_subscription_warning
from app.models.users import User
from app.schemas.user import UserOut

router = APIRouter()


@router.get("/me", response_model=UserOut)
async def read_current_user(current_user: User = Depends(get_current_user)):
    """Get the currently authenticated user's profile."""
    return current_user


@router.get("/me/subscription-status")
async def get_my_subscription_status(
    current_user: User = Depends(get_current_user),
    warning: dict | None = Depends(get_subscription_warning),
):
    """
    Get the current user's tenant subscription status and any warnings.
    
    ✅ NOTE: This endpoint is cached at the dependency level (get_subscription_warning).
    """
    tenant = current_user.tenant
    if tenant is None:
        return {"subscription_status": None, "warning": None}
    
    return {
        "subscription_status": tenant.subscription_status,
        "trial_ends_at": tenant.trial_ends_at,
        "subscription_ends_at": tenant.subscription_ends_at,
        "grace_period_ends_at": tenant.grace_period_ends_at,
        "plan": tenant.plan,
        "warning": warning,
    }
