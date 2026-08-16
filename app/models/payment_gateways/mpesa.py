import enum
from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class MpesaEnvironment(str, enum.Enum):
    sandbox = "sandbox"
    production = "production"


class MpesaConfig(Base, AuditMixin):
    __tablename__ = "mpesa_configs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # ── MANUAL PAYMENT DETAILS (what clients see on invoices) ─────────────
    # ✅ NEW: Which method the tenant configured: "paybill" | "till" | "pochi"
    method_type = Column(String(20), nullable=False, default="paybill")
    business_shortcode = Column(String(20), nullable=True)  # Paybill number
    till_number = Column(String(20), nullable=True)         # Till / Pochi number
    account_number = Column(String(100), nullable=True)     # Account reference (Paybill)
    account_name = Column(String(150), nullable=True)       # Display name for clients

    # ── DARAJA API CREDENTIALS (optional for now — automated STK Push later) ──
    # ✅ CHANGED: nullable=True so tenants can configure manual-only payments
    consumer_key = Column(String(255), nullable=True)
    consumer_secret = Column(String(255), nullable=True)
    passkey = Column(String(255), nullable=True)

    environment = Column(
        Enum(MpesaEnvironment),
        nullable=False,
        default=MpesaEnvironment.sandbox,
    )
    callback_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    tenant = relationship("Tenant", back_populates="mpesa_config")

    __table_args__ = (
        Index("ix_mpesa_configs_tenant_active", "tenant_id", "is_active"),
    )
