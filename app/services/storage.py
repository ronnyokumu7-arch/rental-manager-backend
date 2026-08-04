import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings


# ✅ SECURITY: Strict extension allowlist (no duplicates)
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}

# ✅ SECURITY: MIME type allowlist (prevents .php renamed to .jpg)
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}

# ✅ SECURITY: Category-based size limits (in bytes)
MAX_FILE_SIZES = {
    "avatar": 2 * 1024 * 1024,        # 2MB
    "compliance": 5 * 1024 * 1024,    # 5MB (ID, DL images)
    "contract": 10 * 1024 * 1024,     # 10MB (PDFs)
    "default": 5 * 1024 * 1024,       # 5MB fallback
}

# ✅ SECURITY: Valid categories (prevents arbitrary folder creation)
VALID_CATEGORIES = {"avatar", "compliance", "contract", "misc"}


def _get_settings():
    """Lazy-load settings to avoid circular imports at module load time."""
    return get_settings()


def _get_upload_dir() -> Path:
    """Returns the configured upload directory, creating it if needed."""
    settings = _get_settings()
    upload_dir = Path(settings.uploads_dir).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _get_api_url_base() -> str:
    """Returns the API base used by the authenticated file endpoint."""
    settings = _get_settings()
    return settings.public_url_base.rstrip("/")


def _validate_file(file: UploadFile, category: str) -> str:
    """
    Validates extension, MIME type, and returns the safe lowercase extension.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename."
        )
    
    # 1. Check Extension
    ext = file.filename.rsplit(".", 1)[-1].lower().strip()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{ext}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    
    # 2. Check MIME Type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file content type: {file.content_type}"
        )
    
    return ext


def _get_tenant_folder(tenant_id: int, category: str) -> str:
    """
    ✅ CRITICAL: Enforces multi-tenancy by constructing the folder path internally.
    The router CANNOT pass an arbitrary folder string.
    """
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}"
        )
    
    # Structure: tenant_{id}/{category}
    # e.g., "tenant_42/compliance"
    return f"tenant_{tenant_id}/{category}"


async def upload_file(file: UploadFile, tenant_id: int, category: str = "default") -> str:
    """
    Save an uploaded file with strict multi-tenant isolation and return its
    authenticated API URL. Files remain on the local filesystem for now; no
    third-party object storage is required.
    
    Args:
        file: The uploaded file
        tenant_id: REQUIRED. The tenant that owns this file.
        category: "avatar", "compliance", "contract", or "misc"
    
    Returns:
        Authenticated API URL string for the uploaded file
    """
    # 1. Validate file (extension + MIME)
    ext = _validate_file(file, category)
    
    # 2. Enforce multi-tenant folder structure
    safe_folder = _get_tenant_folder(tenant_id, category)
    
    # 3. Create folder structure
    upload_dir = _get_upload_dir()
    target_dir = upload_dir / safe_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 4. Generate unique filename to prevent collisions
    filename = f"{uuid.uuid4().hex}.{ext}"
    file_path = target_dir / filename
    
    # 5. ✅ Stream file to disk (memory-efficient) with size limit
    max_size = MAX_FILE_SIZES.get(category, MAX_FILE_SIZES["default"])
    
    try:
        total_size = 0
        with open(file_path, "wb") as out_file:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                total_size += len(chunk)
                
                if total_size > max_size:
                    out_file.close()
                    file_path.unlink(missing_ok=True)  # Clean up partial file
                    max_mb = max_size // (1024 * 1024)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large. Maximum size for {category} is {max_mb}MB."
                    )
                
                out_file.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {str(e)}"
        )
    
    # 6. Return the only supported serving path.  Do not return a direct
    # storage URL: IDs and licences must never be public static files.
    api_base = _get_api_url_base()
    return f"{api_base}/api/v1/files/{safe_folder}/{filename}"


def delete_file(url: str, tenant_id: int) -> None:
    """
    Delete a file by its public URL, enforcing tenant ownership.
    
    Safety checks:
    - Validates the URL belongs to the specified tenant
    - Only deletes files within the configured upload directory
    - Prevents path traversal attacks
    - Silently ignores invalid URLs (idempotent)
    """
    if not url:
        return
    
    api_base = _get_api_url_base()
    
    # 1. Ensure URL belongs to our system
    secure_prefix = f"{api_base}/api/v1/files/"
    if not url.startswith(secure_prefix):
        return
    
    # 2. Extract relative path safely
    relative_path = url[len(secure_prefix):].lstrip("/")
    
    # 3. ✅ CRITICAL: Verify the path belongs to the requesting tenant
    if not relative_path.startswith(f"tenant_{tenant_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete files belonging to another tenant"
        )
    
    # 4. Prevent directory traversal
    if ".." in relative_path or relative_path.startswith("/"):
        return
    
    upload_dir = _get_upload_dir()
    file_path = (upload_dir / relative_path).resolve()
    
    # 5. Final safety check: ensure resolved path is strictly inside upload_dir
    try:
        file_path.relative_to(upload_dir)
    except ValueError:
        return  # Path escaped the upload directory - abort
    
    if file_path.exists() and file_path.is_file():
        file_path.unlink()
