"""
Airport Transfer CRUD Router.

✅ DESIGN:
  - Thin delegation: handles HTTP concerns, validation, and tenant isolation.
  - Strict Tenant Scoping: every query filters by current_user.tenant_id.
  - Async-safe: uses proper async session execution.
  - Idempotent creation: prevents duplicate transfers for the same booking.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.models.airport_transfer import AirportTransfer
from app.models.bookings import Booking
from app.models.users import User
from app.schemas.airport_transfer import (
    AirportTransferCreate, 
    AirportTransferOut, 
    AirportTransferUpdate
)
from app.schemas.pagination import PaginatedResponse, paginate_items

router = APIRouter(prefix="/airport-transfers", tags=["airport-transfers"])


# ─── CREATE ───────────────────────────────────────────────────────────────
@router.post("/", response_model=AirportTransferOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_airport_transfer(
    request: Request,
    payload: AirportTransferCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Validate Booking exists and belongs to this tenant
    booking_stmt = select(Booking).where(
        Booking.id == payload.booking_id,
        Booking.tenant_id == current_user.tenant_id,
    )
    booking = (await db.execute(booking_stmt)).scalars().first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found or access denied."
        )

    # 2. Prevent duplicate transfers for the same booking (1:1 relationship)
    dup_stmt = select(AirportTransfer).where(
        AirportTransfer.booking_id == payload.booking_id,
        AirportTransfer.tenant_id == current_user.tenant_id,
    )
    if (await db.execute(dup_stmt)).scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An airport transfer already exists for this booking."
        )

    # 3. Create Transfer
    db_transfer = AirportTransfer(
        **payload.model_dump(),
        tenant_id=current_user.tenant_id,
    )
    db.add(db_transfer)
    await db.commit()
    await db.refresh(db_transfer)

    return db_transfer


# ─── LIST ──────────────────────────────────────────────────────────────────
@router.get("/", response_model=PaginatedResponse[AirportTransferOut])
async def list_airport_transfers(
    request: Request,
    booking_id: int = Query(None),
    flight_number: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(AirportTransfer).where(
        AirportTransfer.tenant_id == current_user.tenant_id
    )
    
    if booking_id is not None:
        stmt = stmt.where(AirportTransfer.booking_id == booking_id)
    if flight_number is not None:
        stmt = stmt.where(AirportTransfer.flight_number.ilike(f"%{flight_number}%"))

    # Get total count for pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Apply pagination
    stmt = stmt.order_by(AirportTransfer.scheduled_pickup_at.desc())
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)

    result = await db.execute(stmt)
    transfers = result.scalars().all()

    return paginate_items(transfers, total=total, page=page, page_size=page_size)


# ─── READ ──────────────────────────────────────────────────────────────────
@router.get("/{transfer_id}", response_model=AirportTransferOut)
async def get_airport_transfer(
    request: Request,
    transfer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(AirportTransfer).where(
        AirportTransfer.id == transfer_id,
        AirportTransfer.tenant_id == current_user.tenant_id,
    )
    transfer = (await db.execute(stmt)).scalars().first()

    if not transfer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Airport transfer not found or access denied."
        )
    
    return transfer


# ─── UPDATE ────────────────────────────────────────────────────────────────
@router.patch("/{transfer_id}", response_model=AirportTransferOut)
@limiter.limit("20/minute")
async def update_airport_transfer(
    request: Request,
    transfer_id: int,
    payload: AirportTransferUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(AirportTransfer).where(
        AirportTransfer.id == transfer_id,
        AirportTransfer.tenant_id == current_user.tenant_id,
    )
    transfer = (await db.execute(stmt)).scalars().first()

    if not transfer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Airport transfer not found or access denied."
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(transfer, field, value)

    await db.commit()
    await db.refresh(transfer)

    return transfer


# ─── DELETE ────────────────────────────────────────────────────────────────
@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_airport_transfer(
    request: Request,
    transfer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(AirportTransfer).where(
        AirportTransfer.id == transfer_id,
        AirportTransfer.tenant_id == current_user.tenant_id,
    )
    transfer = (await db.execute(stmt)).scalars().first()

    if not transfer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Airport transfer not found or access denied."
        )

    await db.delete(transfer)
    await db.commit()
