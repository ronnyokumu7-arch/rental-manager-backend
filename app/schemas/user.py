from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.models.users import UserRole
from app.core.permissions import ALL_PERMISSION_KEYS


class UserBase(BaseModel):
    # ✅ SECURITY FIX: Removed tenant_id - tenant admins cannot specify which tenant to create users in.
    # Only SuperAdminUserCreate (below) allows cross-tenant user creation.
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    role: UserRole = UserRole.tenant_staff
    is_active: bool = True
    is_suspended: bool = False

    phone_number: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    two_factor_enabled: bool = False

    id_number: Optional[str] = None
    dl_number: Optional[str] = None
    dl_expiry: Optional[date] = None
    
    # ✅ NEW: Image URLs for V1 (Base64 or external URLs)
    avatar_url: Optional[str] = None
    id_image_url: Optional[str] = None
    dl_image_url: Optional[str] = None

    # ✅ SECURITY FIX: Validate permissions against master list
    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: List[str]):
        for perm in v:
            if perm not in ALL_PERMISSION_KEYS:
                raise ValueError(f"Invalid permission key: {perm}")
        return v


class UserCreate(UserBase):
    # ✅ REQUIRED: Manual creation always requires a password.
    # (Invite flow uses the separate UserInviteCreate schema below.)
    password: str = Field(min_length=8, max_length=128)


# ✅ NEW: Super Admin Only - Allows cross-tenant user creation
class SuperAdminUserCreate(UserCreate):
    """
    Extended user creation schema for Super Admins only.
    Includes tenant_id to allow creating users in any tenant (e.g., platform onboarding).
    This schema MUST only be used in endpoints protected by super_admin role checks.
    """
    tenant_id: Optional[int] = Field(
        None, 
        description="Super admin only: Create user in a specific tenant"
    )


# ✅ NEW: Admin-side invite creation (name + phone only)
class UserInviteCreate(BaseModel):
    """
    Minimal payload for generating a user invite link.
    The user supplies their own email, documents, and password
    on the public onboarding form (POST /users/accept-invite).
    """
    full_name: str = Field(min_length=1, max_length=255)
    phone_number: Optional[str] = None
    role: UserRole = UserRole.tenant_staff
    department: Optional[str] = None
    job_title: Optional[str] = None


class UserUpdate(BaseModel):
    # ✅ SECURITY FIX: Removed tenant_id to prevent tenant hopping by tenant admins.
    # ✅ SECURITY FIX: Removed security fields (moved to SuperAdminUserUpdate).
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    is_suspended: Optional[bool] = None
    suspension_reason: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)

    phone_number: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    permissions: Optional[List[str]] = None
    two_factor_enabled: Optional[bool] = None

    id_number: Optional[str] = None
    dl_number: Optional[str] = None
    dl_expiry: Optional[date] = None

    # ✅ NEW: Image URLs
    avatar_url: Optional[str] = None
    id_image_url: Optional[str] = None
    dl_image_url: Optional[str] = None

    # UI Preferences
    theme_preference: Optional[str] = Field(None, max_length=20)
    density_preference: Optional[str] = Field(None, max_length=20)

    # ✅ SECURITY FIX: Validate permissions against master list
    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: Optional[List[str]]):
        if v is not None:
            for perm in v:
                if perm not in ALL_PERMISSION_KEYS:
                    raise ValueError(f"Invalid permission key: {perm}")
        return v


# ✅ NEW: Super Admin Only - Allows tenant transfers + security field updates
class SuperAdminUserUpdate(UserUpdate):
    """
    Extended user update schema for Super Admins only.
    Includes tenant_id and security fields to allow legitimate tenant transfers,
    account verification, and security operations.
    This schema MUST only be used in endpoints protected by super_admin role checks.
    """
    tenant_id: Optional[int] = Field(
        None, 
        description="Super admin only: Transfer user to a different tenant"
    )
    
    # ✅ SECURITY FIELDS: Only super admins can modify these
    email_verified: Optional[bool] = None
    phone_verified: Optional[bool] = None
    account_locked_until: Optional[datetime] = None
    invite_token: Optional[str] = None
    invite_expires_at: Optional[datetime] = None
    is_onboarded: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    tenant_id: Optional[int] = None
    full_name: str
    email: EmailStr
    role: UserRole
    is_active: bool
    is_suspended: bool = False
    suspension_reason: Optional[str] = None

    phone_number: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    two_factor_enabled: bool = False
    last_login_at: Optional[datetime] = None

    id_number: Optional[str] = None
    dl_number: Optional[str] = None
    dl_expiry: Optional[date] = None

    created_at: datetime
    updated_at: datetime

    # ✅ NEW: Image URLs
    avatar_url: Optional[str] = None
    id_image_url: Optional[str] = None
    dl_image_url: Optional[str] = None

    # ✅ SECURITY FIX: Removed invite_token (secret, should never be exposed in list/get)
    # ✅ SECURITY FIX: Removed failed_login_attempts (aids brute-force reconnaissance)
    email_verified: bool = False
    phone_verified: bool = False
    account_locked_until: Optional[datetime] = None

    # ✅ Expose Invite State to Frontend (for "Pending" badges)
    invite_expires_at: Optional[datetime] = None
    is_onboarded: bool = False

    # UI Preferences
    theme_preference: Optional[str] = "system"
    density_preference: Optional[str] = "comfortable"
    
    # ✅ NEW: Agency Owner Flag for Frontend UI (Golden Badge)
    is_tenant_owner: bool = False

    model_config = {"from_attributes": True}


# ✅ NEW: Extended UserOut for POST /users/ response
# Only returned by the create endpoint — list/get endpoints still use UserOut
class UserCreateResponse(UserOut):
    """
    Extends UserOut with invite metadata that should ONLY be returned
    immediately after creation (never in list/get responses).
    
    - invite_token: raw token for programmatic use
    - invite_link: pre-built clickable URL ready to share
    """
    invite_token: Optional[str] = Field(
        default=None,
        description="Invite token (only populated when user was created without a password)"
    )
    invite_link: Optional[str] = Field(
        default=None,
        description="Pre-built invite URL ready to share (only populated when invite was generated)"
    )


# ✅ NEW: Public preview for user onboarding
# Returns tenant branding + expected role data for the public intake form
class UserInvitePreviewOut(BaseModel):
    """✅ Public preview for user onboarding. Returns tenant branding + expected role data."""
    # Tenant Branding
    tenant_name: str
    tenant_logo_url: Optional[str] = None
    tenant_phone: Optional[str] = None
    tenant_email: Optional[str] = None
    expires_at: Optional[datetime] = None
    
    # Expected User Data (pre-filled by admin)
    expected_full_name: str
    expected_email: EmailStr
    department: Optional[str] = None
    job_title: Optional[str] = None
    role: UserRole
    
    # UX Flags
    is_driver: bool  # Tells frontend to require DL fields


# ✅ COMPLETELY REWRITTEN: Self-Service Onboarding Payload
class AcceptInvitePayload(BaseModel):
    invite_token: str
    password: str = Field(min_length=8, max_length=128)
    
    # Identity
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone_number: Optional[str] = None
    avatar_url: Optional[str] = None
    
    # Compliance (ID is generally required for staff, DL is conditional)
    id_number: Optional[str] = None
    id_image_url: Optional[str] = None
    dl_number: Optional[str] = None
    dl_image_url: Optional[str] = None
    dl_expiry: Optional[date] = None
