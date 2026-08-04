from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class PaypalConfig(Base, AuditMixin):
    __tablename__ = "paypal_configs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    client_id = Column(String(255), nullable=False)
    client_secret = Column(String(255), nullable=False)
    environment = Column(String(20), nullable=False, default="sandbox")
    is_active = Column(Boolean, nullable=False, default=False)

    tenant = relationship("Tenant", back_populates="paypal_config")

    __table_args__ = (
        Index("ix_paypal_configs_tenant_active", "tenant_id", "is_active"),
    )
