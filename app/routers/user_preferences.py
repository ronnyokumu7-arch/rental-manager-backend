# app/routers/user_preferences.py

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db  # ✅ Updated to async DB path
from app.core.limiter import limiter   # 🚨 Rate limiter
from app.dependencies.auth import get_current_user
from app.models.users import User
from app.schemas.user import UserOut
from app.services.cache import invalidate_user_cache

router = APIRouter(prefix="/user/preferences", tags=["user-preferences"])

@router.get("/", response_model=dict)
@limiter.limit("60/minute")
async def get_preferences(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current user's UI preferences"""
    return {
        "theme": current_user.theme_preference or "system",
        "density": current_user.density_preference or "comfortable",
    }

@router.patch("/", response_model=UserOut)
@limiter.limit("30/minute")
async def update_preferences(
    request: Request,
    theme: str | None = None,
    density: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update current user's UI preferences"""
    if theme is not None:
        if theme not in ["light", "dark", "system"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid theme preference")
        current_user.theme_preference = theme
    
    if density is not None:
        if density not in ["comfortable", "compact"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid density preference")
        current_user.density_preference = density
    
    await db.commit()
    await db.refresh(current_user)
    
    # ✅ Invalidate user cache (UserOut schema includes preferences, so admin lists must be refreshed)
    if current_user.tenant_id:
        await invalidate_user_cache(current_user.tenant_id)
        
    return current_user
