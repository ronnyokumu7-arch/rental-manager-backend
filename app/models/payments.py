import enum
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, Index, CheckConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class PaymentMethod(str, enum.Enum):
    mpesa = "mpesa"
    airtel_money = "airtel_money"
    card = "card"
    paypal = "paypal"
    bank = "bank"
    manual = "manual"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    void = "void"


class VerificationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Payment(Base, AuditMixin):
    """Customer rental invoice payments."""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # Financial Details (with bounded lengths and constraints)
    amount = Column(Numeric(10, 2), nullable=False)
    currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")
    method = Column(Enum(PaymentMethod), nullable=False)
    reference = Column(String(100), nullable=True)  # ✅ Bounded to prevent DB bloat
    
    status = Column(
        Enum(PaymentStatus),
        nullable=False,
        default=PaymentStatus.pending,
        server_default=PaymentStatus.pending.value,
    )
    
    # Metadata & Audit
    paid_at = Column(DateTime(timezone=True), nullable=True)
    recorded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    
    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    # ✅ Added foreign_keys to resolve any potential ambiguity with AuditMixin
    invoice = relationship("Invoice", back_populates="payments", foreign_keys=[invoice_id])
    tenant = relationship("Tenant", back_populates="payments", foreign_keys=[tenant_id])
    recorded_by_user = relationship("User", back_populates="recorded_payments", foreign_keys=[recorded_by])

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # Data Integrity Check Constraint
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        
        # 1. Payment List View with Status/Method Filtering (MOST IMPORTANT)
        Index("ix_payments_tenant_status_created", "tenant_id", "status", "created_at"),
        
        # 2. Revenue Calculations (CRITICAL for financial reports)
        Index("ix_payments_tenant_completed", "tenant_id", "status"),
        
        # 3. Date-Based Revenue Reports
        Index("ix_payments_tenant_paid_at", "tenant_id", "status", "paid_at"),
        
        # 4. Single Payment Lookup (used in void, get, etc.)
        Index("ix_payments_tenant_id", "tenant_id", "id"),
        
        # 5. Invoice-Scoped Payment Lookup (for invoice balance calculations)
        Index("ix_payments_invoice", "invoice_id"),
    )


class PaymentVerification(Base, AuditMixin):
    """SaaS Tenant Subscription M-Pesa / Bank Wire manual verification requests."""
    __tablename__ = "payment_verifications"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Target Subscription Details (bounded)
    target_plan = Column(String(50), nullable=False)
    target_billing_cycle = Column(String(20), nullable=False, default="monthly")
    payment_method = Column(Enum(PaymentMethod), nullable=False)
    
    # Verification Details
    reference_code = Column(String(100), unique=True, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    
    status = Column(
        Enum(VerificationStatus),
        nullable=False,
        default=VerificationStatus.pending,
        server_default=VerificationStatus.pending.value,
        index=True
    )
    rejection_reason = Column(Text, nullable=True)
    
    # Audit & Review
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    
    # ✅ Timestamps removed: created_at and updated_at are now provided by AuditMixin

    # Relationships
    # ✅ Added foreign_keys to resolve any potential ambiguity with AuditMixin
    tenant = relationship("Tenant", back_populates="payment_verifications", foreign_keys=[tenant_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])

    # ✅ CRITICAL INDEXES:
    __table_args__ = (
        # 1. Verification List View with Status Filtering (MOST IMPORTANT)
        Index("ix_verifications_tenant_status_created", "tenant_id", "status", "created_at"),
        
        # 2. Super Admin View of All Verifications
        Index("ix_verifications_status_created", "status", "created_at"),
        
        # 3. Single Verification Lookup
        Index("ix_verifications_id", "id"),
        
        # 4. Reference Code Uniqueness Check (explicit for clarity)
        Index("ix_verifications_reference", "reference_code"),
    )
