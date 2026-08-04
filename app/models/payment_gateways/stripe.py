from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class StripeConfig(Base, AuditMixin):
    __tablename__ = "stripe_configs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    publishable_key = Column(String(255), nullable=False)
    secret_key = Column(String(255), nullable=False)
    webhook_secret = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)

    tenant = relationship("Tenant", back_populates="stripe_config")

    __table_args__ = (
        Index("ix_stripe_configs_tenant_active", "tenant_id", "is_active"),
    )
