# app/services/document_security.py
"""
✅ DOCUMENT SECURITY — content hash + forensic stamp + registry guard.

Ingest pipeline order (every compliance/vetting upload):
  1. Read raw bytes
  2. sha256 of ORIGINAL bytes (identity survives stamping)
  3. Registry duplicate guard: same bytes + DIFFERENT person → ConflictError
  4. Stamp images with forensic watermark (PDFs: hash-only in V1)
  5. Caller uploads stamped bytes via the storage service
  6. register_document(...) — supersedes the old row for owner+slot
     (history kept with is_active=False for fraud investigations)

✅ EXIF/metadata is dropped on stamping (we re-encode, never copy info).
✅ Pillow missing or stamp failure NEVER blocks ingest — hash still guards.
"""
import io
from datetime import datetime, timezone
from hashlib import sha256
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationFailedError
from app.models.document_registry import DocumentRegistry

OWNER_LABEL = {"client": "Client", "driver": "Driver"}

# ✅ Content-type policy: doc slots allow images + PDF; avatar/selfie images only
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def assert_allowed_content_type(content_type: Optional[str], *, allow_pdf: bool) -> None:
    """Typed guard for upload endpoints (mirrors documents.py _assert_image)."""
    allowed = IMAGE_TYPES | ({"application/pdf"} if allow_pdf else set())
    if not content_type or content_type not in allowed:
        hint = "JPG, PNG, WEBP or PDF" if allow_pdf else "JPG, PNG or WEBP"
        raise ValidationFailedError(
            title="Invalid File Type",
            message=f"Only {hint} files are accepted for this document.",
            field_errors={"file": f"Must be one of: {hint}"},
        )


def hash_bytes(data: bytes) -> str:
    """sha256 of the ORIGINAL bytes — the document's identity."""
    return sha256(data).hexdigest()


def stamp_image(
    data: bytes,
    *,
    tenant_name: str,
    owner_ref: str,
    slot: str,
    file_hash: str,
) -> bytes:
    """
    ✅ FORENSIC WATERMARK: semi-transparent diagonal overlay tiled across
    the image. Leaked files become traceable and unusable elsewhere
    (they visibly belong to this tenant + person + slot + moment).

    PDFs / exotic formats pass through unstamped (hash still registered).
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("⚠️ Pillow not installed — storing unstamped (hash still guards)")
        return data

    try:
        base = Image.open(io.BytesIO(data))
        fmt = (base.format or "PNG").upper()
        if fmt == "PDF" or base.mode not in ("RGB", "RGBA", "L"):
            return data
        base = base.convert("RGBA")
        w, h = base.size

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        block = "\n".join([
            tenant_name.upper(),
            owner_ref,
            f"{slot} • {ts}",
            f"sha256:{file_hash[:12]}",
            "FOR VERIFICATION ONLY",
        ])

        font_size = max(16, min(w, h) // 28)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

        # Tile the block across the frame, then rotate for diagonal coverage
        step_x = max(1, w // 2)
        step_y = max(1, h // 2)
        for y in range(-h // 4, h, step_y):
            for x in range(-w // 4, w, step_x):
                draw.multiline_text(
                    (x, y), block, font=font,
                    fill=(255, 255, 255, 70), spacing=font_size // 3,
                )

        overlay = overlay.rotate(30, center=(w // 2, h // 2), expand=False)
        stamped = Image.alpha_composite(base, overlay)

        out = io.BytesIO()
        if fmt in ("JPEG", "JPG"):
            stamped.convert("RGB").save(out, format="JPEG")
        else:
            stamped.save(out, format=fmt)
        return out.getvalue()
    except Exception as e:
        print(f"⚠️ Watermark failed ({e}) — storing unstamped (hash still guards)")
        return data


async def assert_no_cross_owner_duplicate(
    db: AsyncSession,
    *,
    tenant_id: int,
    owner_type: str,
    owner_id: int,
    file_hash: str,
    slot: str,
) -> None:
    """
    ✅ FRAUD CATCH: the exact same file bytes stored under a DIFFERENT person
    in this tenant is a hard conflict. Same owner re-uploading = replace (ok).
    """
    stmt = select(DocumentRegistry).where(
        DocumentRegistry.tenant_id == tenant_id,
        DocumentRegistry.file_hash == file_hash,
        DocumentRegistry.is_active.is_(True),
    )
    row = (await db.execute(stmt)).scalars().first()
    if row and not (row.owner_type == owner_type and row.owner_id == owner_id):
        raise ConflictError(
            title="Document Already Registered",
            message=(
                f"This exact document is already registered to another "
                f"{OWNER_LABEL.get(row.owner_type, 'person').lower()} in your agency. "
                "Duplicate documents are not allowed."
            ),
            details={"slot": slot},
        )


async def register_document(
    db: AsyncSession,
    *,
    tenant_id: int,
    owner_type: str,
    owner_id: int,
    slot: str,
    file_hash: str,
    file_ref: str,
    content_type: Optional[str] = None,
) -> DocumentRegistry:
    """
    ✅ Register the stored artifact. Supersedes previous active rows for
    (owner, slot) — history preserved with is_active=False.
    Caller commits AFTER the owner column is updated (single transaction).
    """
    old_stmt = select(DocumentRegistry).where(
        DocumentRegistry.tenant_id == tenant_id,
        DocumentRegistry.owner_type == owner_type,
        DocumentRegistry.owner_id == owner_id,
        DocumentRegistry.slot == slot,
        DocumentRegistry.is_active.is_(True),
    )
    for old in (await db.execute(old_stmt)).scalars().all():
        old.is_active = False

    row = DocumentRegistry(
        tenant_id=tenant_id,
        owner_type=owner_type,
        owner_id=owner_id,
        slot=slot,
        file_hash=file_hash,
        file_ref=file_ref,
        content_type=content_type,
    )
    db.add(row)
    await db.flush()
    return row


async def secure_prepare(
    data: bytes,
    *,
    db: AsyncSession,
    tenant_id: int,
    owner_type: str,
    owner_id: int,
    slot: str,
    tenant_name: str,
) -> Tuple[bytes, str]:
    """
    ✅ Steps 2–4 in one call: hash → duplicate guard → stamp.
    Returns (bytes_to_upload, file_hash). Caller then uploads + registers.
    """
    file_hash = hash_bytes(data)
    await assert_no_cross_owner_duplicate(
        db,
        tenant_id=tenant_id,
        owner_type=owner_type,
        owner_id=owner_id,
        file_hash=file_hash,
        slot=slot,
    )
    owner_ref = f"{OWNER_LABEL.get(owner_type, 'Person')} #{owner_id}"
    stamped = stamp_image(
        data, tenant_name=tenant_name, owner_ref=owner_ref,
        slot=slot, file_hash=file_hash,
    )
    return stamped, file_hash
