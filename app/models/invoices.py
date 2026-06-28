# app/models/invoices.py
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
import enum

from app.db.base_class import Base

class InvoiceStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    paid = "paid"
    overdue = "overdue"
    void = "void"

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True, index=True)
    
    invoice_number = Column(String(20), unique=True, nullable=False, index=True)
    status = Column(SAEnum(InvoiceStatus), default=InvoiceStatus.draft, nullable=False)
    
    amount_due = Column(DECIMAL(12, 2), default=0, nullable=False)
    amount_paid = Column(DECIMAL(12, 2), default=0, nullable=False)
    currency_code = Column(String(3), default="KES", nullable=False)
    
    due_date = Column(DateTime(timezone=True), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    
    notes = Column(String(500), nullable=True)
    pdf_path = Column(String(500), nullable=True) # For future PDF storage
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    booking = relationship("Booking", back_populates="invoices")
    tenant = relationship("Tenant", back_populates="invoices")
    payments = relationship("Payment", back_populates="invoice")
