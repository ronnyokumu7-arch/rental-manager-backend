import enum

from typing import Optional
from sqlalchemy import Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base

class ClientStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    inactive = "inactive"
    suspended = "suspended"

class Client(Base):
    __tablename__ = "clients"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=False, index=True)
    id_number = Column(String, nullable=True)
    dl_number = Column(String, nullable=True)
    dl_expiry = Column(Date, nullable=True)  # ADD THIS
    status = Column(
        Enum(ClientStatus),
        nullable=False,
        default=ClientStatus.pending,
        server_default=ClientStatus.pending.value,
    )
    residential_address = Column(Text, nullable=True)
    work_address = Column(Text, nullable=True)
    id_image_front = Column(String, nullable=True)
    id_image_back = Column(String, nullable=True)
    dl_image_front = Column(String, nullable=True)
    avatar_image = Column(String, nullable=True)
    next_of_kin_name = Column(String, nullable=True)
    next_of_kin_phone = Column(String, nullable=True)
    is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", name="uq_tenant_phone"),
        UniqueConstraint("tenant_id", "id_number", name="uq_tenant_id_number"),
    )

    tenant = relationship("Tenant", back_populates="clients")
    bookings = relationship("Booking", back_populates="client", cascade="all, delete-orphan")