# app/routers/drivers.py
"""
Staff Drivers CRUD — tenant-scoped (Milestone 2).

✅ SECURITY:
  * Strict tenant isolation via current_user.tenant_id on EVERY query.
    Platform admins (tenant_id NULL) get 403 — no cross-tenant driver PII.
  * List responses use DriverListOut (masked PII, no document keys).
  * Archive is guarded: a driver with active assignments cannot be archived.
  * No hard delete — operational records are preserved (archive only).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.bookings import Booking, BookingStatus
from app.models.drivers import Driver, DriverStatus
from app.models.users import User
from app.schemas.driver import (
    DriverCreate, DriverListOut, DriverOut, DriverUpdate,
)
from app.schemas.pagination import PaginatedResponse, paginate_items

# ✅ PREFIX lives HERE (main.py only adds /api/v1) — matches every other router
router = APIRouter(prefix="/drivers", tags=["drivers"])

ACTIVE_STATUSES = [
    BookingStatus.pending, BookingStatus.confirmed, BookingStatus.active,
]


def _require_tenant_id(current_user: User) -> int:
    """Strict tenant context — platform admins cannot touch driver PII."""
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required.",
        )
    return current_user.tenant_id


async def _get_driver_or_404(
    db: AsyncSession, driver_id: int, tenant_id: int,
) -> Driver:
    stmt = select(Driver).where(
        Driver.id == driver_id,
        Driver.tenant_id == tenant_id,
    )
    driver = (await db.execute(stmt)).scalars().first()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found.",
        )
    return driver


async def _has_active_assignments(db: AsyncSession, driver_id: int) -> bool:
    stmt = select(Booking.id).where(
        Booking.driver_id == driver_id,
        Booking.is_archived == False,
        Booking.status.in_(ACTIVE_STATUSES),
    )
    return (await db.execute(stmt)).scalars().first() is not None


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

@router.get("/", response_model=PaginatedResponse[DriverListOut])
async def list_drivers(
    request: Request,
    status_filter: Optional[DriverStatus] = Query(None, alias="status"),
    include_archived: bool = Query(False),
    search: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Masked list view — raw PII never leaves this endpoint."""
    tenant_id = _require_tenant_id(current_user)

    stmt = select(Driver).where(Driver.tenant_id == tenant_id)
    if not include_archived:
        stmt = stmt.where(Driver.is_archived == False)
    if status_filter is not None:
        stmt = stmt.where(Driver.status == status_filter)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(Driver.full_name.ilike(like), Driver.phone.ilike(like))
        )
    stmt = stmt.order_by(Driver.created_at.desc())

    drivers = (await db.execute(stmt)).scalars().all()
    items = [DriverListOut.from_driver(d) for d in drivers]
    return paginate_items(items, total=len(items), page=page, page_size=page_size)


@router.get("/{driver_id}", response_model=DriverOut)
async def get_driver(
    request: Request,
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full detail (PII + document keys) — strictly within the tenant."""
    tenant_id = _require_tenant_id(current_user)
    return await _get_driver_or_404(db, driver_id, tenant_id)


# ---------------------------------------------------------------------------
# CREATE / UPDATE
# ---------------------------------------------------------------------------

@router.post("/", response_model=DriverOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_driver(
    request: Request,
    payload: DriverCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = _require_tenant_id(current_user)

    driver = Driver(tenant_id=tenant_id, **payload.model_dump())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver


@router.patch("/{driver_id}", response_model=DriverOut)
@limiter.limit("30/minute")
async def update_driver(
    request: Request,
    driver_id: int,
    payload: DriverUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = _require_tenant_id(current_user)
    driver = await _get_driver_or_404(db, driver_id, tenant_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(driver, field, value)

    await db.commit()
    await db.refresh(driver)
    return driver


# ---------------------------------------------------------------------------
# ARCHIVE / RESTORE (no hard delete — records preserved)
# ---------------------------------------------------------------------------

@router.post("/{driver_id}/archive", response_model=DriverOut)
@limiter.limit("10/minute")
async def archive_driver(
    request: Request,
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import datetime, timezone

    tenant_id = _require_tenant_id(current_user)
    driver = await _get_driver_or_404(db, driver_id, tenant_id)

    if driver.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver is already archived.",
        )
    if await _has_active_assignments(db, driver_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver has active assignments. Complete or reassign them first.",
        )

    driver.is_archived = True
    driver.archived_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(driver)
    return driver


@router.post("/{driver_id}/restore", response_model=DriverOut)
@limiter.limit("10/minute")
async def restore_driver(
    request: Request,
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = _require_tenant_id(current_user)
    driver = await _get_driver_or_404(db, driver_id, tenant_id)

    if not driver.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver is not archived.",
        )

    driver.is_archived = False
    driver.archived_at = None
    await db.commit()
    await db.refresh(driver)
    return driver
