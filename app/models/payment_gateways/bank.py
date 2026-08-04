from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class BankAccountConfig(Base, AuditMixin):
    __tablename__ = "bank_account_configs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    bank_name = Column(String(150), nullable=False)
    account_name = Column(String(255), nullable=False)
    account_number = Column(String(255), nullable=False)
    branch_code = Column(String(20), nullable=True)
    swift_code = Column(String(20), nullable=True)
    currency = Column(String(10), nullable=False, default="KES")
    is_primary = Column(Boolean, nullable=False, default=True)

    tenant = relationship("Tenant", back_populates="bank_accounts")

    __table_args__ = (
        Index("ix_bank_configs_tenant", "tenant_id"),
        Index("ix_bank_configs_tenant_primary", "tenant_id", "is_primary"),
        Index("ix_bank_configs_tenant_id", "tenant_id", "id"),
    )
