import enum
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin

class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    tenant_admin = "tenant_admin"
    tenant_staff = "tenant_staff"

class User(Base, AuditMixin):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    
    # Core Identity
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    
    # UI Preferences
    theme_preference = Column(String(20), nullable=True, default="system", server_default="system")
    density_preference = Column(String(20), nullable=True, default="comfortable", server_default="comfortable")
    
    # Contact & Role Details
    phone_number = Column(String(30), nullable=True)
    department = Column(String(100), nullable=True)
    job_title = Column(String(100), nullable=True)
    
    # Security & Access
    permissions = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    two_factor_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    failed_login_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    account_locked_until = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    
    # Compliance (Required for Drivers/Staff)
    id_number = Column(String(50), nullable=True)
    id_image_url = Column(String(500), nullable=True)
    dl_number = Column(String(50), nullable=True)
    dl_image_url = Column(String(500), nullable=True)
    dl_expiry = Column(Date, nullable=True)
    
    # Account Status
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    is_suspended = Column(Boolean, nullable=False, default=False, server_default="false")
    suspension_reason = Column(String(500), nullable=True)
    
    # Verification & Onboarding Lifecycle
    email_verified = Column(Boolean, nullable=False, default=False, server_default="false")
    phone_verified = Column(Boolean, nullable=False, default=False, server_default="false")
    is_onboarded = Column(Boolean, nullable=False, default=False, server_default="false")
    
    # ✅ FIX: Renamed from is_super_tenant_admin to match schema
    is_tenant_owner = Column(Boolean, nullable=False, default=False, server_default="false")
    
    # Invite System
    invite_token = Column(String(100), unique=True, index=True, nullable=True)
    invite_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    role = Column(
        Enum(UserRole),
        nullable=False,
        default=UserRole.tenant_staff,
        server_default=UserRole.tenant_staff.value,
    )
    
    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    tenant = relationship("Tenant", back_populates="users", foreign_keys="[User.tenant_id]")
    password_reset_tokens = relationship(
        "PasswordResetToken",
        foreign_keys="[PasswordResetToken.user_id]",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    activity_logs = relationship(
        "ActivityLog",
        foreign_keys="[ActivityLog.user_id]",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    # ✅ NEW: Refresh token relationship for secure session management
    refresh_tokens = relationship(
        "RefreshToken",
        foreign_keys="[RefreshToken.user_id]",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    assigned_tasks = relationship("Task", foreign_keys="[Task.user_id]", back_populates="user")
    created_tasks = relationship("Task", foreign_keys="[Task.created_by]", back_populates="creator")
    recorded_payments = relationship(
        "Payment",
        foreign_keys="[Payment.recorded_by]",
        back_populates="recorded_by_user",
        cascade="all, delete-orphan",
    )

    # ✅ ADD THESE CRITICAL INDEXES:
    __table_args__ = (
        # 1. User List View with Status Filtering (MOST IMPORTANT)
        Index("ix_users_tenant_status_created", "tenant_id", "is_active", "is_suspended", "created_at"),
        
        # 2. Role Filtering (for admin dashboards)
        Index("ix_users_tenant_role_created", "tenant_id", "role", "created_at"),
        
        # 3. Agency Health Login Tracking (CRITICAL for health endpoint)
        Index("ix_users_tenant_last_login", "tenant_id", "last_login_at"),
        
        # ✅ NEW: Prevent negative login attempts
        CheckConstraint("failed_login_attempts >= 0", name="ck_users_failed_login_attempts_non_negative"),
    )
