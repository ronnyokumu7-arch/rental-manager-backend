import asyncio
import uuid
import warnings
from abc import ABC, abstractmethod
from functools import lru_cache
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

# Cloudinary is an optional dependency; module still works if not installed.
try:
    import cloudinary
    import cloudinary.uploader
    from cloudinary.exceptions import Error as CloudinaryError
    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False


def _get_settings():
    """Lazy-load settings to avoid circular imports at module load time."""
    return get_settings()


def _get_api_url_base() -> str:
    """Returns the API base used by the authenticated file endpoint."""
    return _get_settings().public_url_base.rstrip("/")


def _get_upload_dir() -> Path:
    """Returns the configured upload directory, creating it if needed."""
    upload_dir = Path(_get_settings().uploads_dir).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _validate_file(file: UploadFile, category: str) -> str:
    """
    Validates extension, MIME type, and returns the safe lowercase extension.
    Shared by all backends.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename."
        )

    ext = file.filename.rsplit(".", 1)[-1].lower().strip()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{ext}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

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
    return f"tenant_{tenant_id}/{category}"


# ─────────────────────────────────────────────────────────────────────────────
# BACKEND INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

class StorageBackend(ABC):
    """Abstract storage backend. Both implementations store files under
    `tenant_{id}/{category}/{uuid}.{ext}` and are responsible for their own
    size-limit enforcement."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def upload(
        self,
        file: UploadFile,
        safe_folder: str,   # e.g. "tenant_42/compliance"
        filename: str,      # e.g. "abc123def.jpg"
        category: str,
    ) -> None: ...

    @abstractmethod
    def delete(self, relative_path: str, tenant_id: int) -> None: ...


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL DISK BACKEND (unchanged behavior, extracted)
# ─────────────────────────────────────────────────────────────────────────────

class LocalDiskBackend(StorageBackend):
    @property
    def name(self) -> str:
        return "local"

    async def upload(self, file, safe_folder, filename, category):
        upload_dir = _get_upload_dir()
        target_dir = upload_dir / safe_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename

        max_size = MAX_FILE_SIZES.get(category, MAX_FILE_SIZES["default"])

        try:
            total_size = 0
            with open(file_path, "wb") as out_file:
                while chunk := await file.read(1024 * 1024):
                    total_size += len(chunk)
                    if total_size > max_size:
                        out_file.close()
                        file_path.unlink(missing_ok=True)
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

    def delete(self, relative_path, tenant_id):
        upload_dir = _get_upload_dir()
        file_path = (upload_dir / relative_path).resolve()

        if ".." in relative_path or relative_path.startswith("/"):
            return

        try:
            file_path.relative_to(upload_dir)
        except ValueError:
            return

        if file_path.exists() and file_path.is_file():
            file_path.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# CLOUDINARY BACKEND (private, tenant-mirrored folders)
# ─────────────────────────────────────────────────────────────────────────────

class CloudinaryBackend(StorageBackend):
    """
    Stores files as `type="authenticated"` (private) with `resource_type="auto"`
    so images and PDFs share one code path. Folder structure mirrors tenancy:
      rental/tenant_{id}/{category}/{uuid}   (no extension in Cloudinary)

    Returns the SAME authenticated URL format as local disk:
      {api}/api/v1/files/tenant_{id}/{category}/{uuid}.{ext}
    so the serving router (Stamp 3) can 302-redirect to signed URLs.
    """

    # Top-level Cloudinary folder — keeps tenant files isolated from any other
    # usage on the same account.
    _BUCKET = "rental"

    def __init__(self):
        settings = _get_settings()
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )

    @property
    def name(self) -> str:
        return "cloudinary"

    async def upload(self, file, safe_folder, filename, category):
        # 1. Read all bytes + enforce size limit (files are small, ≤10MB)
        await file.seek(0)
        file_bytes = await file.read()

        max_size = MAX_FILE_SIZES.get(category, MAX_FILE_SIZES["default"])
        if len(file_bytes) > max_size:
            max_mb = max_size // (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size for {category} is {max_mb}MB."
            )

        # 2. Cloudinary public_id strips the extension (resource_type="auto"
        #    handles type detection), so we drop it here.
        uuid_part = filename.rsplit(".", 1)[0]
        public_id = f"{safe_folder}/{uuid_part}"  # e.g. "tenant_42/compliance/abc123"

        def _sync_upload():
            return cloudinary.uploader.upload(
                file_bytes,
                folder=self._BUCKET,
                public_id=public_id,
                resource_type="auto",
                type="authenticated",    # ✅ CRITICAL: private, requires signed URL
                overwrite=False,
                unique_filename=False,
            )

        try:
            await asyncio.to_thread(_sync_upload)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Cloudinary upload failed: {str(e)}"
            )

    def delete(self, relative_path, tenant_id):
        # relative_path = "tenant_{id}/{category}/{filename}"
        parts = relative_path.split("/")
        if len(parts) != 3:
            return
        tenant_folder, category, filename = parts
        uuid_part = filename.rsplit(".", 1)[0]
        public_id = f"{tenant_folder}/{category}/{uuid_part}"

        try:
            cloudinary.uploader.destroy(
                f"{self._BUCKET}/{public_id}",
                resource_type="auto",
            )
        except Exception:
            pass  # idempotent — file may already be gone


# ─────────────────────────────────────────────────────────────────────────────
# BACKEND FACTORY
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_backend() -> StorageBackend:
    """Resolve the storage backend from settings. Falls back gracefully:
      - Cloudinary requested but SDK missing  → local + warning
      - Cloudinary requested but creds empty → local + warning
      - Otherwise                             → whatever was requested
    """
    settings = _get_settings()
    choice = (settings.storage_backend or "local").lower()

    if choice == "cloudinary":
        if not CLOUDINARY_AVAILABLE:
            warnings.warn(
                "STORAGE_BACKEND=cloudinary but `cloudinary` package not installed. "
                "Falling back to local disk. Run `pip install cloudinary` to enable.",
                RuntimeWarning,
            )
            return LocalDiskBackend()

        if not (
            settings.cloudinary_cloud_name
            and settings.cloudinary_api_key
            and settings.cloudinary_api_secret
        ):
            warnings.warn(
                "STORAGE_BACKEND=cloudinary but credentials missing "
                "(CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET). Falling back to local disk.",
                RuntimeWarning,
            )
            return LocalDiskBackend()

        try:
            backend = CloudinaryBackend()
            print("✅ Storage backend: Cloudinary (type=authenticated)")
            return backend
        except Exception as e:
            warnings.warn(
                f"Cloudinary initialization failed ({e}). Falling back to local disk.",
                RuntimeWarning,
            )
            return LocalDiskBackend()

    print("✅ Storage backend: local disk")
    return LocalDiskBackend()


def get_backend() -> StorageBackend:
    """Public accessor for the active storage backend (used by routers)."""
    return _get_backend()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API (signatures UNCHANGED — routers keep working as-is)
# ─────────────────────────────────────────────────────────────────────────────

async def upload_file(file: UploadFile, tenant_id: int, category: str = "default") -> str:
    """
    Save an uploaded file with strict multi-tenant isolation and return its
    authenticated API URL. Backend (local vs Cloudinary) is env-switched;
    stored URL format is identical across backends.

    Args:
        file: The uploaded file
        tenant_id: REQUIRED. The tenant that owns this file.
        category: "avatar", "compliance", "contract", or "misc"

    Returns:
        Authenticated API URL string for the uploaded file
    """
    ext = _validate_file(file, category)
    safe_folder = _get_tenant_folder(tenant_id, category)
    filename = f"{uuid.uuid4().hex}.{ext}"

    backend = _get_backend()
    await backend.upload(file, safe_folder, filename, category)

    api_base = _get_api_url_base()
    return f"{api_base}/api/v1/files/{safe_folder}/{filename}"


def delete_file(url: str, tenant_id: int) -> None:
    """
    Delete a file by its public URL, enforcing tenant ownership.
    Works identically for local and Cloudinary backends.

    Safety checks:
    - Validates the URL belongs to our system
    - Verifies ownership (tenant_id prefix)
    - Prevents path traversal attacks
    - Silently ignores invalid URLs (idempotent)
    """
    if not url:
        return

    api_base = _get_api_url_base()
    secure_prefix = f"{api_base}/api/v1/files/"
    if not url.startswith(secure_prefix):
        return

    relative_path = url[len(secure_prefix):].lstrip("/")

    # ✅ CRITICAL: Verify the path belongs to the requesting tenant
    if not relative_path.startswith(f"tenant_{tenant_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete files belonging to another tenant"
        )

    if ".." in relative_path or relative_path.startswith("/"):
        return

    backend = _get_backend()
    backend.delete(relative_path, tenant_id)
