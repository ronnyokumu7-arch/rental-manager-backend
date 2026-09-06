# app/models/tenant_policies.py
"""
Tenant Business Policy Document — clause-level overrides on platform defaults.

✅ THREE CATEGORIES (mirrors the contract PDF blocks):
  - agency_policies       → Section 4: Specific Agency Policies & Liability Clauses
  - statutory_declaration → Statutory Declaration bullets
  - general_conditions    → General Conditions articles (numbering is positional)

✅ OVERRIDE MODEL:
  - DEFAULT_POLICY_DOCUMENT below is the SINGLE SOURCE OF TRUTH.
  - A row with clause_key set = override of that ONE default clause.
    Missing row ⇒ default inherited verbatim.
  - clause_key NULL = custom clause appended within its category (unlimited).
  - is_active=False on an override ⇒ falls back to the default.
    is_active=False on a custom clause ⇒ hidden.

✅ PARAGRAPH-SAFE: content is rendered with CSS white-space: pre-line,
  so textarea line breaks survive into the PDF exactly as typed.
"""

import enum

from sqlalchemy import (
    Boolean, Column, ForeignKey, Integer, String, Text, Index, text,
)
from sqlalchemy.orm import relationship

from app.db.database import Base, AuditMixin


class PolicyCategory(str, enum.Enum):
    agency_policies = "agency_policies"
    statutory_declaration = "statutory_declaration"
    general_conditions = "general_conditions"


def _clause(key: str, title: str, content: str, order: int) -> dict:
    return {"clause_key": key, "title": title, "content": content, "display_order": order}


# ✅ SINGLE SOURCE OF TRUTH for the default policy document.
DEFAULT_POLICY_DOCUMENT = {
    PolicyCategory.agency_policies: [
        _clause("rental_terms", "General Rental Terms", (
            "The renter must be at least 18 years of age and hold a valid driver's licence. "
            "The vehicle must be used only for lawful purposes and within the agreed rental period. "
            "Sub-letting or use of the vehicle by unauthorised drivers is strictly prohibited."
        ), 1),
        _clause("fuel_policy", "Fuel Policy", (
            "The vehicle is provided with a full tank of fuel and must be returned with a full tank. "
            "Any fuel deficit at the time of return will be charged to the renter at the current market rate "
            "plus a refuelling service fee."
        ), 2),
        _clause("damage_policy", "Damage Policy", (
            "The renter is liable for all damage, loss, or theft occurring during the rental period. "
            "Pre-existing damage will be noted on the vehicle condition report at the time of pickup. "
            "The renter must report any new damage immediately and before returning the vehicle."
        ), 3),
        _clause("late_return", "Late Return Policy", (
            "The vehicle must be returned by the agreed date and time. "
            "Returns after the agreed time will be charged at the daily rate pro-rated per hour. "
            "Please contact us in advance if you require an extension."
        ), 4),
        _clause("deposit", "Security Deposit", (
            "A refundable security deposit is held at the time of booking confirmation. "
            "The deposit will be released within 7 business days of vehicle return, "
            "subject to inspection and clearance of any outstanding charges."
        ), 5),
        _clause("cancellation", "Cancellation Policy", (
            "Cancellations made more than 24 hours before the rental start time are eligible for a full refund. "
            "Cancellations within 24 hours of the rental start time will incur a charge equivalent to one day's rental. "
            "No-shows will be charged the full booking amount."
        ), 6),
    ],
    PolicyCategory.statutory_declaration: [
        _clause("lawful_use", "Lawful Use", "I will use this vehicle strictly for legal purposes.", 1),
        _clause("age_range", "Age Range", "I am between 23 and 70 years old.", 2),
        _clause("fitness", "Physical Fitness", (
            "I am physically fit to drive safely (no vision, hearing, or medical conditions that affect driving)."
        ), 3),
        _clause("convictions", "Driving Record", (
            "I have not been convicted of careless, reckless, or dangerous driving in the last 5 years."
        ), 4),
        _clause("licence_years", "Licence Experience", (
            "I have held a valid driver's license for at least 2 years."
        ), 5),
        _clause("insurance_history", "Insurance History", (
            "No insurance company has ever refused my application, demanded higher premiums, or cancelled my policy."
        ), 6),
    ],
    PolicyCategory.general_conditions: [
        _clause("use_restrictions", "Use Restrictions", (
            "Only you or pre-approved drivers may operate this vehicle. Do not use it for paid transport, towing, "
            "racing, illegal activities, or while under the influence of alcohol/drugs. Keep the vehicle locked and "
            "all documents with you. Subleasing or transferring this contract is prohibited."
        ), 1),
        _clause("vehicle_condition", "Vehicle Condition", (
            "You received the vehicle in good condition. Replace any damaged tires (not normal wear) at your expense. "
            "Do not tamper with the trip recorder or GPS. If the recorder fails, you will be charged for 500 KM per day "
            "until resolved."
        ), 2),
        _clause("extensions", "Extensions", (
            "Want to keep the car longer? Get written approval first and pay the extension fee immediately. "
            "Late returns without approval may be treated as unauthorized use or misappropriation."
        ), 3),
        _clause("payments", "Payments", (
            "You are responsible for all charges, traffic fines, parking tickets, and tolls. Payments must be made "
            "within 48 hours of request. Late payments incur 2% monthly interest."
        ), 4),
        _clause("insurance_accidents", "Insurance & Accidents", (
            "Report any accident, theft, or damage to us within 24 hours. Report to police immediately if there is "
            "injury or theft, and attach the police report. Do not admit fault or settle with third parties without our "
            "written consent. Insurance only covers the agreed rental period."
        ), 5),
        _clause("maintenance_repairs", "Maintenance & Repairs", (
            "Normal wear is our responsibility. For breakdowns or repairs, get written approval from us first. "
            "Keep all receipts and return replaced parts for inspection."
        ), 6),
        _clause("fuel_oil", "Fuel & Oil", (
            "You pay for fuel. Regularly check oil, water, and gearbox levels. Keep fuel receipts if reimbursement is "
            "required per company policy."
        ), 7),
        _clause("liability", "Liability", (
            "You and approved drivers are fully responsible for traffic violations, fines, and damages caused during "
            "the rental period."
        ), 8),
        _clause("contract_validity", "Contract Validity", (
            "This document contains the full agreement. Only written amendments signed by both parties are valid."
        ), 9),
        _clause("disputes", "Disputes", "Any disagreements will be resolved exclusively by the Courts of Kenya.", 10),
        _clause("vehicle_replacement", "Vehicle Replacement", (
            "We reserve the right to replace your vehicle with a similar model if needed (e.g., mechanical issues, "
            "prior hirer delays, or operational requirements)."
        ), 11),
        _clause("data_sharing", "Data Sharing", (
            "We collect your information to manage this rental per Kenya's Data Protection Act. Anonymized data may be "
            "used to improve our platform and services."
        ), 12),
    ],
}


class TenantPolicy(Base, AuditMixin):
    __tablename__ = "tenant_policies"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    # ✅ NEW: which contract block this clause belongs to (String, not DB ENUM —
    # future categories ship without ALTER TYPE migrations).
    category = Column(String(30), nullable=False, index=True)

    # ✅ NEW: identifies the default clause being overridden.
    # NULL = custom/additional clause (unlimited per category).
    clause_key = Column(String(60), nullable=True)

    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    display_order = Column(Integer, nullable=False, default=0)

    # ⚠️ DEPRECATED: legacy column kept nullable for zero-downtime migration.
    # No longer written or read by the application.
    section = Column(String(30), nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="policies", foreign_keys=[tenant_id])

    __table_args__ = (
        # ✅ OVERRIDE RULE: one override per default clause per tenant.
        # Custom clauses (clause_key NULL) are exempt — unlimited additions.
        Index(
            "uq_tenant_policy_clause_override",
            "tenant_id",
            "category",
            "clause_key",
            unique=True,
            postgresql_where=text("clause_key IS NOT NULL"),
        ),
        # Clause list per category in contract order
        Index("ix_policies_tenant_category_order", "tenant_id", "category", "display_order"),
        # Active filtering for contract generation
        Index("ix_policies_tenant_active", "tenant_id", "is_active", "display_order"),
        # Single clause lookup with tenant scoping
        Index("ix_policies_tenant_id", "tenant_id", "id"),
    )
