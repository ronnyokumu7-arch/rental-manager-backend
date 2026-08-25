import enum
from decimal import Decimal

from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, Enum as SAEnum, Text, Index, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.database import Base, AuditMixin


class InvoiceStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    partially_paid = "partially_paid"
    paid = "paid"
    overdue = "overdue"
    void = "void"


class Invoice(Base, AuditMixin):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True)

    # ✅ Core Identity (Tenant-scoped, monthly-resetting format: I{YYYY}{MM}{###})
    invoice_number = Column(String(20), nullable=False, index=True)
    
    status = Column(SAEnum(InvoiceStatus), default=InvoiceStatus.draft, nullable=False)

    # ✅ DOCUMENT TYPE (String, not DB enum → safe evolution, no enum migrations).
    # quotation = pre-acceptance price offer sent to the client (morphs to invoice on accept).
    # invoice   = demand for payment (post-accept, or all legacy rows).
    doc_type = Column(
        String(20), nullable=False,
        default="invoice", server_default="invoice", index=True,
    )

    # Financial Details
    amount_due = Column(Numeric(12, 2), default=0, nullable=False)
    amount_paid = Column(Numeric(12, 2), default=0, nullable=False)
    currency_code = Column(String(3), default="KES", nullable=False)

    discount_amount = Column(Numeric(12, 2), default=0, nullable=False)
    discount_reason = Column(Text, nullable=True)

    # Dates
    due_date = Column(DateTime(timezone=True), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    notes = Column(String(500), nullable=True)
    pdf_path = Column(String(500), nullable=True)

    # Public Sharing
    share_token = Column(String(36), unique=True, nullable=True, index=True)
    share_token_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    booking = relationship("Booking", back_populates="invoices", foreign_keys=[booking_id])
    tenant = relationship("Tenant", back_populates="invoices", foreign_keys=[tenant_id])
    payments = relationship("Payment", back_populates="invoice")

    @property
    def remaining_balance(self) -> Decimal:
        return max(Decimal("0"), self.amount_due - (self.amount_paid or Decimal("0")))

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_number", name="uq_tenant_invoice_number"),
        Index("ix_invoices_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_invoices_tenant_overdue", "tenant_id", "status", "due_date"),
        Index("ix_invoices_tenant_id", "tenant_id", "id"),
        Index("ix_invoices_token_expires", "share_token", "share_token_expires_at"),
        Index("ix_invoices_tenant_paid", "tenant_id", "status", "paid_at"),
        Index("ix_invoices_booking", "booking_id"),
        # ✅ Quotation pipeline: find a booking's live quotation to morph on accept
        Index("ix_invoices_booking_doctype", "booking_id", "doc_type"),
    )
