# app/models/tenant_policies.py

import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import relationship

from app.db.database import Base, AuditMixin


class PolicySection(str, enum.Enum):
    rental_terms = "rental_terms"
    fuel_policy = "fuel_policy"
    damage_policy = "damage_policy"
    late_return = "late_return"
    deposit = "deposit"
    cancellation = "cancellation"
    other = "other"


DEFAULT_POLICIES = [
    {
        "section": PolicySection.rental_terms,
        "title": "General Rental Terms",
        "content": (
            "The renter must be at least 18 years of age and hold a valid driver's licence. "
            "The vehicle must be used only for lawful purposes and within the agreed rental period. "
            "Sub-letting or use of the vehicle by unauthorised drivers is strictly prohibited."
        ),
        "display_order": 1,
    },
    {
        "section": PolicySection.fuel_policy,
        "title": "Fuel Policy",
        "content": (
            "The vehicle is provided with a full tank of fuel and must be returned with a full tank. "
            "Any fuel deficit at the time of return will be charged to the renter at the current market rate "
            "plus a refuelling service fee."
        ),
        "display_order": 2,
    },
    {
        "section": PolicySection.damage_policy,
        "title": "Damage Policy",
        "content": (
            "The renter is liable for all damage, loss, or theft occurring during the rental period. "
            "Pre-existing damage will be noted on the vehicle condition report at the time of pickup. "
            "The renter must report any new damage immediately and before returning the vehicle."
        ),
        "display_order": 3,
    },
    {
        "section": PolicySection.late_return,
        "title": "Late Return Policy",
        "content": (
            "The vehicle must be returned by the agreed date and time. "
            "Returns after the agreed time will be charged at the daily rate pro-rated per hour. "
            "Please contact us in advance if you require an extension."
        ),
        "display_order": 4,
    },
    {
        "section": PolicySection.deposit,
        "title": "Security Deposit",
        "content": (
            "A refundable security deposit is held at the time of booking confirmation. "
            "The deposit will be released within 7 business days of vehicle return, "
            "subject to inspection and clearance of any outstanding charges."
        ),
        "display_order": 5,
    },
    {
        "section": PolicySection.cancellation,
        "title": "Cancellation Policy",
        "content": (
            "Cancellations made more than 24 hours before the rental start time are eligible for a full refund. "
            "Cancellations within 24 hours of the rental start time will incur a charge equivalent to one day's rental. "
            "No-shows will be charged the full booking amount."
        ),
        "display_order": 6,
    },
]


class TenantPolicy(Base, AuditMixin):
    __tablename__ = "tenant_policies"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    section = Column(Enum(PolicySection), nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    display_order = Column(Integer, nullable=False, default=0)
    
    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    # ✅ Added foreign_keys to resolve any potential ambiguity with AuditMixin.created_by
    tenant = relationship("Tenant", back_populates="policies", foreign_keys=[tenant_id])

    # ✅ CRITICAL INDEXES:
    __table_args__ = (
        # 1. Policy List View (MOST IMPORTANT)
        # Query: WHERE tenant_id = ? ORDER BY display_order ASC
        # Used in: list_policies endpoint
        Index("ix_policies_tenant_display_order", "tenant_id", "display_order"),
        
        # 2. Single Policy Lookup with Tenant Scoping
        # Query: WHERE tenant_id = ? AND id = ?
        # Used in: update_policy, toggle_policy, delete_policy
        Index("ix_policies_tenant_id", "tenant_id", "id"),
        
        # 3. Active Policy Filtering (for contract generation)
        # Query: WHERE tenant_id = ? AND is_active = true ORDER BY display_order
        # Used when generating contracts to include only active policies
        Index("ix_policies_tenant_active", "tenant_id", "is_active", "display_order"),
        
        # 4. Section-Based Lookup (for policy management)
        # Query: WHERE tenant_id = ? AND section = ?
        # Used when admins want to view/edit policies by section
        Index("ix_policies_tenant_section", "tenant_id", "section"),
    )
