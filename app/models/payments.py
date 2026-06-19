import enum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class PaymentMethod(str, enum.Enum):
    mpesa = "mpesa"
    manual = "manual"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")
    method = Column(Enum(PaymentMethod), nullable=False)
    reference = Column(String, nullable=True)
    status = Column(
        Enum(PaymentStatus),
        nullable=False,
        default=PaymentStatus.pending,
        server_default=PaymentStatus.pending.value,
    )
    paid_at = Column(DateTime(timezone=True), nullable=True)
    recorded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    invoice = relationship("Invoice", back_populates="payments")
    tenant = relationship("Tenant", back_populates="payments")
    recorded_by_user = relationship("User", back_populates="recorded_payments")