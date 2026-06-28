import enum

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class BookingStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    destination = Column(String, nullable=True)
    pickup_location = Column(String, nullable=True)
    return_location = Column(String, nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    total_amount = Column(Integer, nullable=False)
    currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")
    status = Column(
        Enum(BookingStatus),
        nullable=False,
        default=BookingStatus.pending,
        server_default=BookingStatus.pending.value,
    )
    is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    share_token = Column(String(36), unique=True, nullable=True, index=True)

    tenant = relationship("Tenant", back_populates="bookings")
    client = relationship("Client", back_populates="bookings")
    vehicle = relationship("Vehicle", back_populates="bookings")
    contract = relationship("Contract", back_populates="booking", uselist=False, cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="booking", cascade="all, delete-orphan")
