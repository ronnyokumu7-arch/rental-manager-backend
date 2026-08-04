from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base, AuditMixin


class RefreshToken(Base, AuditMixin):
    """
    Stores hashed opaque refresh tokens to enable secure rotation and revocation.
    Using opaque tokens instead of JWTs for refresh prevents replay attacks and 
    allows immediate invalidation (e.g., on logout or suspected compromise).
    """
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    
    # ✅ FIX: Make tenant_id nullable so Super Admins (tenant_id=None) can have refresh tokens
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # The hashed version of the opaque token (never store plain text)
    token_hash = Column(String(255), unique=True, index=True, nullable=False)
    
    # Expiration and Revocation tracking
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked = Column(Boolean, nullable=False, default=False, index=True)
    
    # ✅ Security Audit: Track device and IP for session management
    user_agent = Column(String(500), nullable=True)  # Browser/device info
    ip_address = Column(String(45), nullable=True)  # Supports IPv6 (max 45 chars)
    
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    
    # ✅ Timestamp removed: created_at is now provided by AuditMixin
    
    # Relationships
    # ✅ Added foreign_keys to resolve ambiguity with AuditMixin.created_by
    user = relationship("User", back_populates="refresh_tokens", foreign_keys=[user_id])
    tenant = relationship("Tenant", back_populates="refresh_tokens", foreign_keys=[tenant_id])

    # ✅ INDEXES & CONSTRAINTS:
    __table_args__ = (
        # Data Integrity Check Constraint
        CheckConstraint("expires_at > created_at", name="ck_refresh_tokens_valid_expiry"),
        
        # 1. Fast lookup for validation: WHERE token_hash = ? AND revoked = false AND expires_at > ?
        Index("ix_refresh_tokens_validation", "token_hash", "revoked", "expires_at"),
        
        # 2. Cleanup job: Find expired tokens to purge (global)
        Index("ix_refresh_tokens_expires", "expires_at"),
        
        # 3. Tenant-scoped cleanup and session management (works fine with nullable tenant_id)
        # Query: WHERE tenant_id = ? AND revoked = false AND expires_at > ?
        Index("ix_refresh_tokens_tenant_active", "tenant_id", "revoked", "expires_at"),
        
        # 4. User session management: List/revoke all tokens for a user
        Index("ix_refresh_tokens_user", "user_id", "revoked"),
        
        # 5. Active sessions per user (for "show my active sessions" UI)
        # Query: WHERE user_id = ? AND revoked = false AND expires_at > ? ORDER BY created_at DESC
        Index("ix_refresh_tokens_user_active", "user_id", "revoked", "expires_at", "created_at"),
    )
