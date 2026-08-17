# app/models/commission_payment.py
import enum

from sqlalchemy import (
    Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Index,
)
from sqlalchemy.orm import relationship

from app.db.database import Base, AuditMixin


class CommissionPaymentStatus(str, enum.Enum):
    pending = "pending"      # Tenant submitted, awaiting your verification
    verified = "verified"    # You confirmed receipt → events flip to paid → unlock
    rejected = "rejected"    # Code didn't match → tenant notified, still owes


class CommissionPayment(Base, AuditMixin):
    """
    A tenant's self-reported commission payment (sent to the platform Paybill).
    On verification, the tenant's oldest unpaid CommissionEvents flip to 'paid'
    and the soft-lock lifts instantly.
    """
    __tablename__ = "commission_payments"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    amount = Column(Numeric(10, 2), nullable=False)
    currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")

    # ✅ The M-Pesa confirmation code the tenant submits (e.g., QFG34HJ8L)
    reference = Column(String(100), nullable=False)

    status = Column(
        Enum(CommissionPaymentStatus),
        nullable=False,
        default=CommissionPaymentStatus.pending,
    )

    # Who submitted (tenant user) and who verified (super admin)
    submitted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(String(500), nullable=True)  # rejection reason / admin note

    tenant = relationship("Tenant", backref="commission_payments")
    verifier = relationship("User", foreign_keys=[verified_by])

    __table_args__ = (
        # ✅ Your verification queue: "show me all pending payments, oldest first"
        Index("ix_commission_payments_status_created", "status", "created_at"),
        # ✅ Tenant's own payment history
        Index("ix_commission_payments_tenant_created", "tenant_id", "created_at"),
    )
