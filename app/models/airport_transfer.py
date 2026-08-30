"""
Airport Transfer model — 1:1 extension of the core Booking record.

✅ DESIGN:
  - Holds specific flight/airport data that doesn't belong in the generic Booking table.
  - 1:1 relationship with Booking (unique constraint on booking_id).
  - Tenant-scoped for multi-tenant isolation.
  - Migration-safe String enums (no ALTER TYPE needed for new directions).
"""
import enum
from sqlalchemy import (
    Column, Integer, String, Numeric, Text, Enum, ForeignKey,
    Index, UniqueConstraint, CheckConstraint, DateTime
)
from sqlalchemy.orm import relationship

from app.db.database import Base, AuditMixin


class TransferDirection(str, enum.Enum):
    """
    ✅ Application-level validator for transfer direction.
    Stored as String(20) in DB.
    """
    airport_pickup = "airport_pickup"       # Picking up client from airport
    airport_dropoff = "airport_dropoff"     # Dropping off client at airport
    both = "both"                           # Round trip (if applicable in v1)


class AirportTransfer(Base, AuditMixin):
    __tablename__ = "airport_transfers"

    id = Column(Integer, primary_key=True, index=True)

    # ✅ Tenant & Booking Links
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(
        Integer, ForeignKey("bookings.id", ondelete="CASCADE"), 
        nullable=False, unique=True, index=True
    )

    # ✅ Flight & Airport Details
    flight_number = Column(String(20), nullable=True, index=True)  # e.g., KQ100
    airline = Column(String(50), nullable=True)                    # e.g., Kenya Airways
    terminal = Column(String(20), nullable=True)                   # e.g., Terminal 1A, 1B, 1C (JKIA)
    airport_code = Column(String(10), nullable=True, index=True)   # IATA code e.g., NBO, LHR
    
    # ✅ Time & Scheduling (Crucial for Dispatch)
    # Note: The main Booking model has 'pickup_at', but we keep this here for quick dispatch queries.
    scheduled_pickup_at = Column(DateTime(timezone=True), nullable=False, index=True)
    flight_arrival_at = Column(DateTime(timezone=True), nullable=True) # For tracking delays on pickups

    # ✅ Location Details (Overrides or supplements Booking pickup/destination)
    city = Column(String(100), nullable=True)                      # e.g., Nairobi, Mombasa
    pickup_location = Column(String(255), nullable=True)           # Detailed address/hotel/terminal
    drop_off_location = Column(String(255), nullable=True)         # Detailed address/hotel
    
    # ✅ Transfer Type
    direction = Column(
        String(20), nullable=False, default=TransferDirection.airport_pickup,
        server_default=TransferDirection.airport_pickup
    )

    # ✅ v1 Pricing Variables (Defined by user/admin per trip)
    # These are added to the base route price to calculate the final total.
    toll_fees = Column(Numeric(10, 2), default=0.00, nullable=False)
    airport_parking_fees = Column(Numeric(10, 2), default=0.00, nullable=False)
    
    # ✅ Notes
    notes = Column(Text, nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="airport_transfers", foreign_keys=[tenant_id])
    booking = relationship("Booking", back_populates="airport_transfer", foreign_keys=[booking_id])

    # ✅ Constraints & Indexes
    __table_args__ = (
        # Data Integrity
        CheckConstraint("toll_fees >= 0", name="ck_airport_transfers_toll_fees_non_negative"),
        CheckConstraint("airport_parking_fees >= 0", name="ck_airport_transfers_parking_fees_non_negative"),
        
        # 1. Fast lookup by tenant and booking
        Index("ix_airport_transfers_tenant_booking", "tenant_id", "booking_id"),
        
        # 2. Fast lookup by flight number for dispatchers
        Index("ix_airport_transfers_flight_number", "tenant_id", "flight_number"),

        # 3. Dispatch scheduling (finding trips by time)
        Index("ix_airport_transfers_dispatch", "tenant_id", "scheduled_pickup_at"),
    )
