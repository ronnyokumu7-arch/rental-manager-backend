"""
Image processing service for client onboarding uploads.

Responsibilities:
  - Decode ANY smartphone/scanner format (HEIC, HEIF, AVIF, WebP, BMP, TIFF, PNG, JPEG)
  - Normalize EXIF orientation (rotated phone photos become upright)
  - Flatten alpha to white background (PNG transparency → clean JPEG)
  - Downscale longest edge to 1600px (enough for legible IDs/DLs)
  - Re-encode as JPEG with quality stepping until ≤ 4 MB stored
  - Pass PDFs through untouched (capped at 10 MB by storage layer)

Output is always a (bytes, extension) tuple ready for storage.
"""
from __future__ import annotations

import io
from typing import Tuple

from fastapi import HTTPException, UploadFile, status

# Optional imports — only loaded if image processing is actually invoked
try:
    from PIL import Image, ImageOps, UnidentifiedImageError
    from pillow_heif import register_heif_opener
    PIL_AVAILABLE = True
    # Register HEIC/HEIF opener so Pillow can decode iPhone photos
    register_heif_opener()
except ImportError:
    PIL_AVAILABLE = False

# Target: stored file ≤ 4 MB (compliance docs) or ≤ 10 MB (avatars stay small)
MAX_STORED_BYTES_COMPLIANCE = 4 * 1024 * 1024
MAX_STORED_BYTES_AVATAR = 1 * 1024 * 1024
MAX_LONG_EDGE = 1600  # pixels — enough for legible ID/DL text at print quality

# Formats we decode via Pillow (after registering HEIC/HEIF)
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "heif", "avif", "bmp", "tiff", "tif"}
PDF_EXTENSIONS = {"pdf"}


async def process_upload(file: UploadFile, category: str = "compliance") -> Tuple[bytes, str]:
    """
    Process an uploaded file for storage.

    Images: decode → normalize → downscale → JPEG re-encode with quality stepping.
    PDFs: pass through bytes unchanged (storage layer caps at 10 MB).

    Returns:
        (bytes, extension) tuple. Extension is always "jpg" for images, "pdf" for PDFs.

    Raises:
        HTTPException 400 if the file cannot be decoded (corrupt, zero-byte, etc.)
    """
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename.")

    ext = file.filename.rsplit(".", 1)[-1].lower().strip() if "." in file.filename else ""

    await file.seek(0)
    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")

    # ── PDFs: pass through untouched ──────────────────────────────────
    if ext in PDF_EXTENSIONS or (file.content_type or "").startswith("application/pdf"):
        return file_bytes, "pdf"

    # ── Images: decode + normalize + compress ─────────────────────────
    if not PIL_AVAILABLE:
        # Pillow not installed — fall back to raw bytes (best-effort)
        return file_bytes, ext

    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.load()  # force full decode so corrupt files fail here, not at storage
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot decode image: {type(e).__name__}. Try a different file.",
        )

    # 1. EXIF orientation (rotated phone photos become upright)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass  # no EXIF or unparseable — keep original orientation

    # 2. Flatten alpha to white background (PNG/WebP transparency → clean JPEG)
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # 3. Downscale longest edge to MAX_LONG_EDGE (preserves aspect ratio)
    w, h = img.size
    longest = max(w, h)
    if longest > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / longest
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)

    # 4. Quality-step JPEG encoding until ≤ target size
    target_bytes = (
        MAX_STORED_BYTES_AVATAR if category == "avatar"
        else MAX_STORED_BYTES_COMPLIANCE
    )

    for quality in (88, 80, 72, 64, 56, 48):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True, subsampling="4:2:0")
        encoded = buf.getvalue()
        if len(encoded) <= target_bytes:
            return encoded, "jpg"

    # 5. Last resort: further downscale to fit the target
    for scale in (0.9, 0.8, 0.7, 0.6, 0.5):
        smaller = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        smaller.save(buf, format="JPEG", quality=64, optimize=True, subsampling="4:2:0")
        encoded = buf.getvalue()
        if len(encoded) <= target_bytes:
            return encoded, "jpg"

    # Absolute fallback: return whatever we got at lowest quality
    return encoded, "jpg"
