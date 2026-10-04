# app/routers/contract/actions.py
"""
✅ CONTRACT ACTIONS — void / regenerate / share-link / send-to-client.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ AUDIT (Phase B):
  - send_contract_to_client awaited defensively (sync OR async safe).
  - Email failure after commit → typed ServerError with manual alternative.
  - share-link response carries a success envelope.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.errors import BadRequestError, NotFoundError, ServerError
from app.core.limiter import limiter
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.contracts import Contract, ContractStatus
from app.models.users import User
from app.models.vehicles import Vehicle
from app.schemas.contract import ContractOut
from app.services.cache import invalidate_contract_cache
from app.services.contracts import create_contract_for_booking, render_and_store_contract_pdf
from app.services.email import send_contract_to_client
from ._helpers import get_authorized_contract_async

router = APIRouter()
settings = get_settings()


@router.post("/{contract_id}/void", response_model=ContractOut)
@limiter.limit("10/minute")
async def void_contract(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    contract = await get_authorized_contract_async(contract_id, current_user, db)
    
    if contract.status == ContractStatus.void:
        raise BadRequestError(
            title="Already Void",
            message="This contract is already void.",
        )
    if contract.status == ContractStatus.signed:
        raise BadRequestError(
            title="Signed Contracts Can't Be Voided",
            message="A signed contract is a legal record. It can't be voided from here.",
        )
        
    contract.status = ContractStatus.void
    await db.commit()
    
    # ✅ FIXED: Re-fetch with eager loading so ContractOut serialization can't crash
    stmt = select(Contract).options(
        selectinload(Contract.booking).selectinload(Booking.client)
    ).where(Contract.id == contract.id)
    result = await db.execute(stmt)
    contract = result.scalars().unique().first()
    
    await invalidate_contract_cache(current_user.tenant_id)
    return contract


@router.post("/bookings/{booking_id}/regenerate", response_model=ContractOut)
@limiter.limit("10/minute")
async def regenerate_contract(
    request: Request,
    booking_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    # ✅ Verify booking belongs to tenant
    booking_stmt = select(Booking).where(
        Booking.id == booking_id,
        Booking.tenant_id == current_user.tenant_id
    )
    booking_result = await db.execute(booking_stmt)
    booking = booking_result.scalars().first()
    
    if not booking:
        raise NotFoundError(
            title="Booking Not Found",
            message="We couldn't find this booking, or you may not have access to it.",
        )
        
    # ✅ Verify existing contract belongs to tenant before deleting
    existing_stmt = select(Contract).where(
        Contract.booking_id == booking_id,
        Contract.tenant_id == current_user.tenant_id
    )
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalars().first()
    
    if existing:
        await db.delete(existing)
        await db.commit()
        
    # ✅ FAST: creates + commits the row only — returns in milliseconds
    new_contract = await create_contract_for_booking(booking, db)

    # ✅ FIXED: Re-fetch with eager loading so ContractOut serialization can't crash
    stmt = select(Contract).options(
        selectinload(Contract.booking).selectinload(Booking.client)
    ).where(Contract.id == new_contract.id)
    result = await db.execute(stmt)
    new_contract = result.scalars().unique().first()

    await invalidate_contract_cache(current_user.tenant_id)

    # ✅ SLOW: Chromium PDF render happens AFTER the response is sent
    background_tasks.add_task(render_and_store_contract_pdf, new_contract.id)

    return new_contract


@router.post("/{contract_id}/share-link", response_model=dict)
@limiter.limit("20/minute")
async def generate_share_link(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    contract = await get_authorized_contract_async(contract_id, current_user, db)
    
    if contract.status == ContractStatus.void:
        raise BadRequestError(
            title="Void Contract",
            message="Void contracts cannot be shared.",
        )

    contract.share_token = str(uuid.uuid4())
    contract.share_token_expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    if contract.status == ContractStatus.draft:
        contract.status = ContractStatus.sent

    await db.commit()
    await db.refresh(contract)
    await invalidate_contract_cache(current_user.tenant_id)

    return {
        "type": "success",
        "title": "Share Link Ready",
        "message": "The signing link is valid for 30 days.",
        "share_token": contract.share_token,
        "share_url": f"{settings.frontend_url.rstrip('/')}/contracts/view/{contract.share_token}",
        "expires_at": contract.share_token_expires_at,
    }


@router.post("/{contract_id}/send-to-client", response_model=ContractOut)
@limiter.limit("10/minute")
async def send_contract_to_client_endpoint(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    # ✅ Optimized: Fetch contract, booking, client, and vehicle in ONE query
    stmt = select(Contract).options(
        selectinload(Contract.booking).selectinload(Booking.client),
        selectinload(Contract.booking).selectinload(Booking.vehicle)
    ).where(
        Contract.id == contract_id,
        Contract.tenant_id == current_user.tenant_id
    )
    result = await db.execute(stmt)
    contract = result.scalars().unique().first()
    
    if not contract:
        raise NotFoundError(
            title="Contract Not Found",
            message="We couldn't find this contract, or you may not have access to it.",
        )
        
    booking = contract.booking
    client = booking.client
    vehicle = booking.vehicle
    
    if not client or not client.email:
        raise BadRequestError(
            title="Client Email Missing",
            message="This client has no email address on file. Add one before sending the contract — or use the share link instead.",
        )

    if not contract.share_token:
        contract.share_token = str(uuid.uuid4())
        contract.share_token_expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    contract.status = ContractStatus.sent
    await db.commit()
    await db.refresh(contract)
    await invalidate_contract_cache(current_user.tenant_id)

    share_url = f"{settings.frontend_url.rstrip('/')}/contracts/view/{contract.share_token}"

    # ✅ Phase B: sync/async-safe call + honest failure (was: silent no-send or raw 500)
    try:
        maybe_coro = send_contract_to_client(
            to=client.email,
            client_name=client.full_name,
            contract_number=contract.contract_number,
            vehicle=f"{vehicle.make} {vehicle.model} ({vehicle.plate_number})" if vehicle else "N/A",
            start_date=str(booking.start_date),
            end_date=str(booking.end_date),
            total_amount=str(booking.total_amount),
            currency=booking.currency_code,
            contract_url=share_url,
        )
        if asyncio.iscoroutine(maybe_coro):
            await maybe_coro
    except Exception as e:
        print(f"⚠️ Contract email failed for contract {contract.id}: {e}")
        raise ServerError(
            title="Email Failed to Send",
            message="The contract is ready and marked as sent, but the email didn't go out. Use the share link to send it manually.",
        )

    return contract
