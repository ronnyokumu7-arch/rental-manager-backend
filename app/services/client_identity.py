# app/services/client_identity.py
"""
✅ IDENTITY ENGINE (per-tenant).

Hard blocks : phone / email / identity slot (id_type+id_number) / dl_number
Soft flags  : F1 self-referential emergency contact,
              F2 emergency contact recycled from another client's phone.

Emergency contacts are EXEMPT from hard blocks by design.
"""
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clients import Client, IdType


@dataclass
class IdentityConflict:
    field: str
    message: str


# ─── NORMALIZERS ─────────────────────────────────────────────────────────────

def normalize_phone(value: Optional[str]) -> Optional[str]:
    """Canonical form: +2547XX... for KE numbers; digits/+ only."""
    if value is None:
        return None
    cleaned = re.sub(r"[^\d+]", "", value.strip())
    if not cleaned:
        return None
    if cleaned.startswith("0"):
        cleaned = "+254" + cleaned[1:]
    elif cleaned.startswith("254"):
        cleaned = "+" + cleaned
    return cleaned


def _phone_variants(value: Optional[str]) -> list[str]:
    """All raw spellings that normalize to the same canonical number."""
    canonical = normalize_phone(value)
    if not canonical:
        return []
    variants = {canonical}
    if canonical.startswith("+254"):
        variants.add("0" + canonical[4:])   # 07XX...
        variants.add(canonical[1:])         # 2547XX...
    return list(variants)


def normalize_email(value: Optional[str]) -> Optional[str]:
    return value.strip().lower() if value else None


def normalize_doc(value: Optional[str]) -> Optional[str]:
    return value.strip().upper() if value else None


# ─── HARD BLOCKS ─────────────────────────────────────────────────────────────

async def check_identity_conflicts(
    db: AsyncSession,
    tenant_id: int,
    *,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    id_type: Optional[IdType] = None,
    id_number: Optional[str] = None,
    dl_number: Optional[str] = None,
    exclude_client_id: Optional[int] = None,   # for updates (don't fight yourself)
) -> list[IdentityConflict]:
    """Returns every hard-block collision within THIS tenant only."""
    conflicts: list[IdentityConflict] = []

    base = select(Client).where(Client.tenant_id == tenant_id)
    if exclude_client_id is not None:
        base = base.where(Client.id != exclude_client_id)

    # 1) Phone (variant-aware, uses ix on phone)
    variants = _phone_variants(phone)
    if variants:
        row = (await db.execute(base.where(Client.phone.in_(variants)))).scalars().first()
        if row:
            suffix = " (archived record)" if row.is_archived else ""
            conflicts.append(IdentityConflict(
                "phone", f"A client with this phone number already exists{suffix}."
            ))

    # 2) Email (case-insensitive)
    em = normalize_email(email)
    if em:
        row = (await db.execute(base.where(func.lower(Client.email) == em))).scalars().first()
        if row:
            conflicts.append(IdentityConflict(
                "email", "A client with this email address already exists."
            ))

    # 3) Identity slot (type-aware)
    doc = normalize_doc(id_number)
    if doc and id_type:
        row = (await db.execute(
            base.where(Client.id_type == id_type, Client.id_number == doc)
        )).scalars().first()
        if row:
            label = "National ID" if id_type == IdType.national_id else "Passport"
            conflicts.append(IdentityConflict(
                "id_number", f"A client with this {label} number already exists."
            ))

    # 4) Driver's licence (only when provided)
    dl = normalize_doc(dl_number)
    if dl:
        row = (await db.execute(base.where(Client.dl_number == dl))).scalars().first()
        if row:
            conflicts.append(IdentityConflict(
                "dl_number", "A client with this driver's licence number already exists."
            ))

    return conflicts


# ─── SOFT FLAGS (never block — raise suspicion) ─────────────────────────────

async def compute_risk_flags(
    db: AsyncSession,
    tenant_id: int,
    *,
    own_phone: Optional[str] = None,
    next_of_kin_phone: Optional[str] = None,
    exclude_client_id: Optional[int] = None,
) -> tuple[bool, Optional[str]]:
    """
    F1: emergency contact == the client's own number.
    F2: emergency contact == another client's identity phone in this tenant.
    Returns (is_flagged, flag_notes).
    """
    notes: list[str] = []
    kin = normalize_phone(next_of_kin_phone)

    if kin:
        if kin == normalize_phone(own_phone):
            notes.append("Client listed their own number as the emergency contact.")
        else:
            q = select(Client).where(
                Client.tenant_id == tenant_id,
                Client.phone.in_(_phone_variants(kin)),
            )
            if exclude_client_id is not None:
                q = q.where(Client.id != exclude_client_id)
            match = (await db.execute(q)).scalars().first()
            if match:
                notes.append(
                    f"Emergency contact number matches an existing client (#{match.id}). "
                    "Verify the relationship before activation."
                )

    if notes:
        return True, " ".join(notes)
    return False, None
