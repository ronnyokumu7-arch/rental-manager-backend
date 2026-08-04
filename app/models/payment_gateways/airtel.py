from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class AirtelMoneyConfig(Base, AuditMixin):
    __tablename__ = "airtel_money_configs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    api_key = Column(String(255), nullable=False)
    api_secret = Column(String(255), nullable=False)
    merchant_code = Column(String(50), nullable=False)
    country_code = Column(String(5), nullable=False, default="KE")
    callback_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    tenant = relationship("Tenant", back_populates="airtel_config")

    __table_args__ = (
        Index("ix_airtel_configs_tenant_active", "tenant_id", "is_active"),
    )
