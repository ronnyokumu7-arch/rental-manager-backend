# app/routers/client/management.py
"""
✅ CLIENT CRUD — identity engine + risk flags + tenant-scoped caching.

✅ ERROR SYSTEM: typed AppException subclasses (app.core.errors).
✅ UPGRADE:
  - Name split: full_name concatenated server-side from first/last.
  - Driving arrangement: self_drive enforces DL data; own_driver creates a
    linked personal Driver (contracted) in the SAME transaction.
  - Identity engine now covers cross-entity (client ↔ driver) collisions.
  - FIXED RUNTIME BUG: BookingStatus.ongoing doesn't exist (AttributeError → 500).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ConflictError, ValidationFailedError
from app.db.database import get_db
from app.core.limiter import limiter
from app.dependencies.auth import get_current_user
from app.dependencies.subscription import require_active_subscription
from app.dependencies.commission_lock import require_not_commission_locked
from app.dependencies.tenant import TenantScope, get_tenant_scope, require_mutation_tenant_scope
from app.models.users import User
from app.models.clients import Client
from app.models.bookings import Booking, BookingStatus
from app.models.drivers import Driver, DriverEmploymentType, DriverVerificationStatus
from app.schemas.client import ClientCreate, ClientOut, ClientUpdate
from app.schemas.pagination import PaginatedResponse, paginate_items, paginate_cached_items
from app.services.cache import get_cached_client_list, set_cached_client_list, invalidate_client_cache
from app.services.client_identity import (
    collect_client_identity_conflicts,
    collect_driver_identity_conflicts,
    compute_risk_flags,
)
from app.services.client_tasks import ClientTaskService
from ._helpers import get_authorized_client_async

router = APIRouter()

# ✅ LIVE STATUSES that block archive/delete (pending counts — quotation in flight)
ACTIVE_BLOCKING_STATUSES = [
    BookingStatus.pending,
    BookingStatus.confirmed,
    BookingStatus.active,
]


def _conflict_error(conflicts, title: str = "Duplicate Client Details") -> ConflictError:
    """Identity-engine conflicts → structured 409 (first message surfaces, all preserved)."""
    messages = [c.message for c in conflicts]
    return ConflictError(
        title=title,
        message=messages[0] if messages else "A person with these details already exists.",
        details={"conflicts": messages},
    )


def _concat_full_name(first_name: str, last_name: str) -> str:
    return " ".join(part for part in [first_name.strip(), last_name.strip()] if part)


def _assert_self_drive_data(client_in: ClientCreate) -> None:
    """✅ self_drive clients must carry licence DATA at creation (images can follow)."""
    if client_in.driving_arrangement != "self_drive":
        return
    missing: dict[str, str] = {}
    if not client_in.dl_number:
        missing["dl_number"] = "Self-drive clients must provide their licence number"
    if not client_in.dl_expiry:
        missing["dl_expiry"] = "Self-drive clients must provide their licence expiry date"
    if missing:
        raise ValidationFailedError(
            title="Driver's Licence Required",
            message="Self-drive clients must provide their driver's licence details.",
            field_errors=missing,
        )


async def _assert_no_live_bookings(db: AsyncSession, client_id: int, action: str) -> None:
    """✅ FIXED: was BookingStatus.ongoing (AttributeError → 500 on every call)."""
    live_booking = (await db.execute(
        select(Booking).where(
            Booking.client_id == client_id,
            Booking.status.in_(ACTIVE_BLOCKING_STATUSES),
        )
    )).scalars().first()
    if live_booking:
        raise BadRequestError(
            title="Client Has Active Bookings",
            message=f"This client has active bookings. Complete or cancel them before {action} this client.",
        )


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
    # ✅ IDENTITY ENGINE: hard blocks incl. cross-entity (phone/email/id slot/dl)
    conflicts = await collect_client_identity_conflicts(
        db,
        scope.tenant_id,
        phone=client.phone,
        email=client.email,
        id_type=client.id_type,
        id_number=client.id_number,
        dl_number=client.dl_number,
    )
    if conflicts:
        raise _conflict_error(conflicts)

    # ✅ ARRANGEMENT GUARDS
    _assert_self_drive_data(client)

    # ✅ OWN DRIVER: pre-check the driver's identity BEFORE touching the client
    if client.driving_arrangement == "own_driver" and client.driver:
        driver_conflicts = await collect_driver_identity_conflicts(
            db,
            scope.tenant_id,
            phone=client.driver.phone,
            id_number=client.driver.id_number,
            dl_number=client.driver.dl_number,
        )
        if driver_conflicts:
            raise _conflict_error(driver_conflicts, title="Duplicate Driver Details")

    # ✅ RISK FLAGS: soft suspicion (F1 self-reference, F2 recycled emergency #)
    is_flagged, flag_notes = await compute_risk_flags(
        db,
        scope.tenant_id,
        own_phone=client.phone,
        next_of_kin_phone=client.next_of_kin_phone,
    )

    client_data = client.model_dump(exclude={"driver"})
    client_data["full_name"] = _concat_full_name(client.first_name, client.last_name)

    db_client = Client(
        **client_data,
        tenant_id=scope.tenant_id,
        is_flagged=is_flagged,
        flag_notes=flag_notes,
    )
    db.add(db_client)
    await db.flush()  # ✅ populate db_client.id for the driver link

    # ✅ PERSONAL DRIVER: linked record in the SAME transaction
    if client.driving_arrangement == "own_driver" and client.driver:
        block = client.driver
        db_driver = Driver(
            tenant_id=scope.tenant_id,
            client_id=db_client.id,
            full_name=block.full_name,
            phone=block.phone,
            id_number=block.id_number,
            dl_number=block.dl_number,
            dl_expiry=block.dl_expiry,
            dl_issued_date=block.dl_issued_date,
            employment_type=DriverEmploymentType.contracted.value,
            verification_status=DriverVerificationStatus.unverified.value,
        )
        db.add(db_driver)

    try:
        await db.commit()
        await db.refresh(db_client)
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            title="Client Already Exists",
            message="A client with these details already exists. Check the existing record before adding another client.",
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

    # ✅ NAME SPLIT: if either name part changes, recompute full_name from the
    # merged state (legacy rows with NULL parts fall back to existing parts).
    if {"first_name", "last_name"} & update_data.keys():
        merged_first = update_data.get("first_name", client.first_name) or ""
        merged_last = update_data.get("last_name", client.last_name) or ""
        concatenated = _concat_full_name(merged_first, merged_last)
        if concatenated:
            update_data["full_name"] = concatenated
        update_data.pop("full_name", None) if not concatenated else None

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
        conflicts = await collect_client_identity_conflicts(
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
            raise _conflict_error(conflicts)

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
        raise ConflictError(
            title="Client Already Exists",
            message="A client with these details already exists. Check the existing record before updating this client.",
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
        raise BadRequestError(
            title="Already Archived",
            message="This client is already archived.",
        )

    # ✅ Check for live bookings (FIXED: was BookingStatus.ongoing → AttributeError)
    await _assert_no_live_bookings(db, client.id, "archiving")

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
        raise BadRequestError(
            title="Nothing to Restore",
            message="This client is not archived, so there's nothing to restore.",
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
        raise BadRequestError(
            title="Archive First",
            message="Archive this client before deleting them.",
        )

    # ✅ Check for live bookings (FIXED: was BookingStatus.ongoing → AttributeError)
    await _assert_no_live_bookings(db, client.id, "deleting")

    try:
        await db.delete(client)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise BadRequestError(
            title="Client Has History",
            message="This client has past bookings and cannot be deleted. Keep the record archived instead.",
        )

    # ✅ Invalidate cache
    await invalidate_client_cache(client.tenant_id)
