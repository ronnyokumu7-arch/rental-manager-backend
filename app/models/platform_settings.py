# app/models/platform_settings.py
from sqlalchemy import CheckConstraint, Column, Integer, Numeric, String

from app.db.database import Base, AuditMixin


class PlatformSettings(Base, AuditMixin):
    """
    ✅ SINGLETON: Global platform configuration.
    This table is constrained to exactly ONE row (id=1).
    It holds the PAYG commission rules and the platform's own payment details
    (where tenants send the money they owe you).
    """
    __tablename__ = "platform_settings"

    # Always 1. The CheckConstraint below enforces this.
    id = Column(Integer, primary_key=True)

    # ── PAYG COMMISSION RULES ─────────────────────────────────────
    # The amount charged per started trip (default KES 150)
    commission_amount = Column(
        Numeric(10, 2), nullable=False, default=150.00, server_default="150.00"
    )
    
    # Days a tenant has to pay before soft-lock kicks in (default 3)
    grace_period_days = Column(
        Integer, nullable=False, default=3, server_default="3"
    )

    # ── PLATFORM PAYMENT DETAILS (Shown on /commission/pay) ───────
    # The Paybill number tenants will send their commission to
    platform_paybill = Column(String(50), nullable=True)
    
    # The account name on the Paybill (e.g., "Rental Garage Ltd")
    platform_account_name = Column(String(150), nullable=True)
    
    # Fallback contact for tenants who have questions about their bill
    platform_phone = Column(String(20), nullable=True)
    platform_email = Column(String(150), nullable=True)

    __table_args__ = (
        # ✅ ENFORCEMENT: Prevents accidental creation of a second row.
        # If someone tries `PlatformSettings(id=2)`, the DB will reject it.
        CheckConstraint("id = 1", name="ck_platform_settings_singleton"),
    )
