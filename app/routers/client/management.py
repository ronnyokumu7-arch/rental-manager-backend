from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.dependencies.commission_lock import require_not_commission_locked
from app.dependencies.tenant import TenantScope, get_tenant_scope, require_mutation_tenant_scope
from app.models.users import User
from app.models.clients import Client
from app.models.bookings import Booking, BookingStatus
from app.schemas.client import ClientCreate, ClientOut, ClientUpdate
from app.schemas.pagination import PaginatedResponse, paginate_items, paginate_cached_items
from app.services.cache import get_cached_client_list, set_cached_client_list, invalidate_client_cache
from app.services.client_identity import check_identity_conflicts, compute_risk_flags
from app.services.client_tasks import ClientTaskService
from ._helpers import get_authorized_client_async

router = APIRouter()


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

@router.post("/", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("100/minute")
async def create_client(
    request: Request,
    client: ClientCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_not_commission_locked),
    scope: TenantScope = Depends(require_mutation_tenant_scope),
):
    # ✅ IDENTITY ENGINE: hard blocks (phone/email/id slot/dl, per-tenant)
    conflicts = await check_identity_conflicts(
        db,
        scope.tenant_id,
        phone=client.phone,
        email=client.email,
        id_type=client.id_type,
        id_number=client.id_number,
        dl_number=client.dl_number,
    )
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=[c.message for c in conflicts],
        )

    # ✅ RISK FLAGS: soft suspicion (F1 self-reference, F2 recycled emergency #)
    is_flagged, flag_notes = await compute_risk_flags(
        db,
        scope.tenant_id,
        own_phone=client.phone,
        next_of_kin_phone=client.next_of_kin_phone,
    )

    db_client = Client(
        **client.model_dump(),
        tenant_id=scope.tenant_id,
        is_flagged=is_flagged,
        flag_notes=flag_notes,
    )
    db.add(db_client)

    try:
        await db.commit()
        await db.refresh(db_client)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A client with these details already exists.",
        )

    await ClientTaskService.on_client_created(db, db_client, db_client.tenant_id)

    # ✅ Invalidate cache
    await invalidate_client_cache(db_client.tenant_id)

    return db_client


# ---------------------------------------------------------------------------
# READ (Tenant-Scoped Caching)
# ---------------------------------------------------------------------------

@router.get("/", response_model=PaginatedResponse[ClientOut])
@limiter.limit("60/minute")
async def list_clients(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
    scope: TenantScope = Depends(get_tenant_scope),
):
    """
    ✅ SECURITY: Manual tenant-scoped caching.
    """
    # Check cache first
    cached = await get_cached_client_list(scope.tenant_id, archived=False)
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)

    # Cache miss: fetch from DB
    stmt = select(Client).where(Client.is_archived == False)
    if scope.tenant_id is not None:
        stmt = stmt.where(Client.tenant_id == scope.tenant_id)
    stmt = stmt.order_by(Client.created_at.desc())

    result = await db.execute(stmt)
    clients = result.scalars().all()

    # Write to cache (5-minute TTL)
    await set_cached_client_list(scope.tenant_id, archived=False, clients=clients)

    return paginate_items(clients, total=len(clients), page=page, page_size=page_size)


@router.get("/archived", response_model=PaginatedResponse[ClientOut])
@limiter.limit("60/minute")
async def list_archived_clients(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
    scope: TenantScope = Depends(get_tenant_scope),
):
    """
    ✅ SECURITY: Manual tenant-scoped caching.
    """
    # Check cache first
    cached = await get_cached_client_list(scope.tenant_id, archived=True)
    if cached is not None:
        return paginate_cached_items(cached, page=page, page_size=page_size)

    # Cache miss: fetch from DB
    stmt = select(Client).where(Client.is_archived == True)
    if scope.tenant_id is not None:
        stmt = stmt.where(Client.tenant_id == scope.tenant_id)
    stmt = stmt.order_by(Client.archived_at.desc())

    result = await db.execute(stmt)
    clients = result.scalars().all()

    # Write to cache
    await set_cached_client_list(scope.tenant_id, archived=True, clients=clients)

    return paginate_items(clients, total=len(clients), page=page, page_size=page_size)


@router.get("/{client_id}", response_model=ClientOut)
@limiter.limit("60/minute")
async def get_client(
    request: Request,
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    return await get_authorized_client_async(client_id, current_user, db)


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

@router.patch("/{client_id}", response_model=ClientOut)
@limiter.limit("30/minute")
async def update_client(
    request: Request,
    client_id: int,
    updates: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)
    update_data = updates.model_dump(exclude_unset=True)

    # ✅ Build the FINAL values (existing merged with updates) so we can
    # check identity uniqueness against the post-update state, excluding self.
    final_phone = update_data.get("phone", client.phone)
    final_email = update_data.get("email", client.email)
    final_id_type = update_data.get("id_type", client.id_type)
    final_id_number = update_data.get("id_number", client.id_number)
    final_dl_number = update_data.get("dl_number", client.dl_number)
    final_next_of_kin_phone = update_data.get("next_of_kin_phone", client.next_of_kin_phone)

    # ✅ IDENTITY ENGINE: only run if any identity field is being touched
    identity_keys = {"phone", "email", "id_type", "id_number", "dl_number"}
    if identity_keys & update_data.keys():
        conflicts = await check_identity_conflicts(
            db,
            client.tenant_id,
            phone=final_phone,
            email=final_email,
            id_type=final_id_type,
            id_number=final_id_number,
            dl_number=final_dl_number,
            exclude_client_id=client.id,
        )
        if conflicts:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[c.message for c in conflicts],
            )

    # Apply updates
    for field, value in update_data.items():
        setattr(client, field, value)

    # ✅ RECOMPUTE FLAGS if emergency contact or phone changed
    if {"phone", "next_of_kin_phone"} & update_data.keys():
        is_flagged, flag_notes = await compute_risk_flags(
            db,
            client.tenant_id,
            own_phone=final_phone,
            next_of_kin_phone=final_next_of_kin_phone,
            exclude_client_id=client.id,
        )
        client.is_flagged = is_flagged
        client.flag_notes = flag_notes

    try:
        await db.commit()
        await db.refresh(client)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A client with these details already exists.",
        )

    # ✅ Invalidate cache
    await invalidate_client_cache(client.tenant_id)

    return client


# ---------------------------------------------------------------------------
# ARCHIVE / RESTORE / DELETE
# ---------------------------------------------------------------------------

@router.post("/{client_id}/archive", response_model=ClientOut)
@limiter.limit("10/minute")
async def archive_client(
    request: Request,
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)

    if client.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client is already archived."
        )

    # ✅ Check for active bookings
    active_bookings_stmt = select(Booking).where(
        Booking.client_id == client.id,
        Booking.status.in_([BookingStatus.confirmed, BookingStatus.ongoing])
    )
    active_bookings = (await db.execute(active_bookings_stmt)).scalars().first()
    if active_bookings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot archive client with active bookings. Please complete or cancel bookings first."
        )

    client.is_archived = True
    client.archived_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(client)

    # ✅ Invalidate cache
    await invalidate_client_cache(client.tenant_id)

    return client


@router.post("/{client_id}/restore", response_model=ClientOut)
@limiter.limit("10/minute")
async def restore_client(
    request: Request,
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)

    if not client.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client is not archived."
        )

    client.is_archived = False
    client.archived_at = None
    await db.commit()
    await db.refresh(client)

    # ✅ Invalidate cache
    await invalidate_client_cache(client.tenant_id)

    return client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_client(
    request: Request,
    client_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_active_subscription),
):
    client = await get_authorized_client_async(client_id, current_user, db)

    if not client.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client must be archived before deletion."
        )

    # ✅ Check for active bookings
    active_bookings_stmt = select(Booking).where(
        Booking.client_id == client.id,
        Booking.status.in_([BookingStatus.confirmed, BookingStatus.ongoing])
    )
    active_bookings = (await db.execute(active_bookings_stmt)).scalars().first()
    if active_bookings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete client with active bookings. Please complete or cancel bookings first."
        )

    try:
        await db.delete(client)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete client with historical bookings. Please archive instead."
        )

    # ✅ Invalidate cache
    await invalidate_client_cache(client.tenant_id)
