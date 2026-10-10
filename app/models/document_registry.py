# app/models/document_registry.py
"""
✅ DOCUMENT REGISTRY — content-level dedupe + fraud catch + audit trail.

Every ingested compliance/vetting file is registered by sha256 of its
ORIGINAL bytes (pre-watermark). Rules:
  * Same hash + same owner + same slot  → replace (slot upsert, supersede row)
  * Same hash + DIFFERENT owner (tenant) → hard ConflictError at ingest
    ("This document is already registered to another person")
  * Rows are NEVER deleted — superseded rows keep is_active=False for
    fraud investigations (who uploaded what, when).
"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Integer, String, UniqueConstraint, Index,
)

from app.db.database import Base, AuditMixin


class DocumentRegistry(Base, AuditMixin):
    __tablename__ = "document_registry"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)

    # Polymorphic owner: 'client' | 'driver'
    owner_type = Column(String(20), nullable=False)
    owner_id = Column(Integer, nullable=False)

    # Slot names: id_front | id_back | dl_front | avatar | selfie_with_id
    slot = Column(String(30), nullable=False)

    # sha256 of ORIGINAL uploaded bytes (watermark changes bytes, so we
    # hash BEFORE stamping — identity survives the stamp)
    file_hash = Column(String(64), nullable=False)

    # Stored (stamped) artifact reference — URL for clients, key for drivers
    file_ref = Column(String(500), nullable=False)
    content_type = Column(String(100), nullable=True)

    # One active row per (owner, slot); history kept with is_active=False
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('client', 'driver')",
            name="ck_doc_registry_owner_type_valid",
        ),
        # Dedupe lookup: "has anyone in this tenant stored these bytes?"
        Index("ix_doc_registry_tenant_hash_active", "tenant_id", "file_hash", "is_active"),
        # Owner history lookup (fraud investigations)
        Index("ix_doc_registry_owner", "owner_type", "owner_id"),
    )
