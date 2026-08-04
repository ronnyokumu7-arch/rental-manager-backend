from sqlalchemy import Column, Integer, String, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin


class RoleTemplate(Base, AuditMixin):
    __tablename__ = "role_templates"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # ✅ Bounded to 100 chars (e.g., "Driver", "Accountant", "Fleet Manager")
    job_title = Column(String(100), nullable=False)
    
    # Optional description for template documentation
    description = Column(String(500), nullable=True)
    
    # The default permissions assigned to users with this job title
    permissions = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)

    # ✅ Consistent relationship pattern (matches other models)
    # ✅ Added foreign_keys to resolve any potential ambiguity with AuditMixin.created_by
    tenant = relationship("Tenant", back_populates="role_templates", foreign_keys=[tenant_id])

    # ✅ CRITICAL INDEXES & CONSTRAINTS:
    __table_args__ = (
        # ✅ Tenant-scoped uniqueness: Each tenant can only have ONE template per job title
        UniqueConstraint("tenant_id", "job_title", name="uq_tenant_role_template_job_title"),
        
        # 1. Find Template by Job Title (CRITICAL for user creation)
        # Query: WHERE tenant_id = ? AND job_title = ?
        # Used in create_user endpoint to assign default permissions
        Index("ix_role_templates_tenant_job_title", "tenant_id", "job_title"),
        
        # 2. Single Template Lookup with Tenant Scoping
        # Query: WHERE tenant_id = ? AND id = ?
        # Used in update_template endpoint
        Index("ix_role_templates_tenant_id", "tenant_id", "id"),
    )
