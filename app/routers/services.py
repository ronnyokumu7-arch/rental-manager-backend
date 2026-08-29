# app/routers/services.py
"""
Service Catalog Export — feeds frontend selectors & future duty scheduler.

✅ PHASE 1: Returns the self-drive service with basic metadata.
No pricing config lookup (Phase 1 has no config tables).
Future phases will add pro-driver, wedding-chauffeur, etc.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.users import User

# ✅ PREFIX lives HERE (main.py only adds /api/v1) — matches every other router
router = APIRouter(prefix="/services", tags=["services"])


@router.get("/", response_model=dict)
async def list_services(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ✅ PHASE 1: Returns the self-drive service catalog entry.
    No tenant-scoped config (Phase 1 pricing is pure, no config tables).
    """
    # ✅ PHASE 1: Static self-drive service definition
    selfdrive_service = {
        "key": "selfdrive",
        "label": "Self-Drive Rental",
        "category": "rental",
        "is_live": True,
        "description": "24-hour day billing, optional driver assignment",
    }

    services = [selfdrive_service]
    categories = {
        "rental": [selfdrive_service],
    }

    return {"services": services, "categories": categories}
