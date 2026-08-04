from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Index, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base, AuditMixin


class PasswordResetToken(Base, AuditMixin):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # ✅ Bounded to 256 chars (SHA-256 = 64, SHA-512 = 128, safe headroom)
    token_hash = Column(String(256), nullable=False, unique=True)
    
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="password_reset_tokens", foreign_keys=[user_id])

    # ✅ ADD THESE CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # Data Integrity Check Constraint
        CheckConstraint("expires_at > created_at", name="ck_reset_tokens_valid_expiry"),
        
        # 1. Token Validation (MOST IMPORTANT)
        # Query: WHERE token_hash = ? AND expires_at > ? AND used_at IS NULL
        # This is the primary query when a user submits a password reset form
        Index("ix_reset_tokens_validation", "token_hash", "expires_at", "used_at"),
        
        # 2. Find Unused Tokens per User
        # Query: WHERE user_id = ? AND used_at IS NULL ORDER BY created_at DESC
        # Used to check if a user already has an active reset token
        Index("ix_reset_tokens_user_unused", "user_id", "used_at", "created_at"),
        
        # 3. Cleanup Expired Tokens (for background jobs)
        # Query: WHERE expires_at < ? OR used_at IS NOT NULL
        # Used by daily cleanup tasks to remove old tokens
        Index("ix_reset_tokens_expires", "expires_at"),
    )
