import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class VehicleStatus(str, enum.Enum):
    available = "available"
    rented = "rented"
    maintenance = "maintenance"
    retired = "retired"


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    make = Column(String, nullable=False)
    model = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    plate_number = Column(String, nullable=False)
    vin = Column(String, nullable=True)
    status = Column(
        Enum(VehicleStatus),
        nullable=False,
        default=VehicleStatus.available,
        server_default=VehicleStatus.available.value,
    )
    daily_rate = Column(Numeric(10, 2), nullable=False)
    insurance_doc = Column(String, nullable=True)
    registration_doc = Column(String, nullable=True)
    inspection_doc = Column(String, nullable=True)
    insurance_expiry = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "plate_number", name="uq_tenant_plate"),
        UniqueConstraint("tenant_id", "vin", name="uq_tenant_vin"),
    )

    tenant = relationship("Tenant", back_populates="vehicles")
    bookings = relationship("Booking", back_populates="vehicle", cascade="all, delete-orphan")