# app/models/task.py

import enum
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Boolean, Text, Index
from sqlalchemy.orm import relationship
from app.db.database import Base, AuditMixin

class TaskStatus(str, enum.Enum):
    unassigned = "unassigned"
    pending = "pending"
    in_progress = "in_progress"
    in_review = "in_review"
    blocked = "blocked"
    completed = "completed"

class TaskCategory(str, enum.Enum):
    fleet = "fleet"
    finance = "finance"
    hr = "hr"
    booking = "booking"
    compliance = "compliance"
    maintenance = "maintenance"
    operations = "operations"
    other = "other"

class TaskPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"

class Task(Base, AuditMixin):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # SECURITY & ISOLATION
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    
    # FUTURE-PROOFING: Multi-branch support (Nullable for now)
    location_id = Column(Integer, nullable=True, index=True)
    
    # USER ASSIGNMENT & UNASSIGNED POOL
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # ✅ created_by removed: provided by AuditMixin
    
    # SMART ROUTING: Remembers what role this task was meant for if unassigned
    requires_role = Column(String(50), nullable=True)
    
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # ✅ UPDATED: Now uses strict TaskCategory enum instead of raw String
    category = Column(Enum(TaskCategory), nullable=False, default=TaskCategory.operations)
    
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.pending)
    priority = Column(Enum(TaskPriority), default=TaskPriority.medium)
    
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    is_system_generated = Column(Boolean, default=True)
    
    # DATA LIFECYCLE: For the 30-90 day archiving strategy
    is_archived = Column(Boolean, default=False, server_default="false")
    
    # Polymorphic references
    target_type = Column(String(50), nullable=True)  
    target_id = Column(Integer, nullable=True)
    
    # ✅ Timestamps removed: provided by AuditMixin
    
    # RELATIONSHIPS
    tenant = relationship("Tenant", back_populates="tasks", foreign_keys=[tenant_id])
    user = relationship("User", foreign_keys=[user_id], back_populates="assigned_tasks")
    # ✅ creator relationship now points to the AuditMixin's created_by column
    creator = relationship("User", foreign_keys="[Task.created_by]", back_populates="created_tasks")

    # ✅ CRITICAL INDEXES
    __table_args__ = (
        # 1. Staff Task Feed (MOST IMPORTANT)
        Index("ix_tasks_user_feed", "tenant_id", "user_id", "is_archived", "status", "due_date"),
        
        # 2. Admin View of Specific User's Tasks
        Index("ix_tasks_tenant_user", "tenant_id", "user_id", "is_archived", "due_date"),
        
        # 3. Unassigned Pool (CRITICAL for task claiming)
        Index("ix_tasks_unassigned_pool", "tenant_id", "status", "is_archived", "created_at"),
        
        # 4. Single Task Lookup with Tenant Scoping
        Index("ix_tasks_tenant_id", "tenant_id", "id"),
        
        # 5. Claim Task (atomic check)
        Index("ix_tasks_claimable", "id", "tenant_id", "status"),
        
        # 6. Category Filtering (for task feed filters)
        Index("ix_tasks_tenant_category", "tenant_id", "category", "is_archived"),
        
        # 7. Overdue Task Detection (for daily scheduler)
        Index("ix_tasks_overdue", "tenant_id", "status", "due_date", "is_archived"),
    )
