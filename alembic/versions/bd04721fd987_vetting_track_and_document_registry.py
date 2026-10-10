"""vetting track and document registry

Revision ID: bd04721fd987
Revises: 459a8feb0e50
Create Date: 2026-10-10 12:33:21.092640

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd04721fd987'
down_revision: Union[str, Sequence[str], None] = '459a8feb0e50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ═══════════════════════════════════════════════════════════
    # CLIENTS: name split + DL issue date + driving arrangement + vetting track
    # ═══════════════════════════════════════════════════════════
    op.add_column("clients", sa.Column("first_name", sa.String(length=120), nullable=True))
    op.add_column("clients", sa.Column("last_name", sa.String(length=120), nullable=True))
    op.add_column("clients", sa.Column("dl_issued_date", sa.Date(), nullable=True))
    
    # ✅ NEW: Driving arrangement column
    op.add_column("clients", sa.Column(
        "driving_arrangement", sa.String(length=20),
        nullable=False, server_default="self_drive",
    ))
    op.create_check_constraint(
        "ck_clients_driving_arrangement_valid", "clients",
        "driving_arrangement IN ('self_drive', 'own_driver', 'chauffeur')",
    )

    op.add_column("clients", sa.Column(
        "verification_status", sa.String(length=20),
        nullable=False, server_default="unverified",
    ))
    op.add_column("clients", sa.Column("verification_token", sa.String(length=64), nullable=True))
    op.add_column("clients", sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("selfie_with_id_image", sa.String(length=500), nullable=True))
    op.add_column("clients", sa.Column("vetted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("vetted_by", sa.Integer(), nullable=True))
    op.add_column("clients", sa.Column("rejection_notes", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_clients_vetted_by", "clients", "users",
        ["vetted_by"], ["id"], ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_clients_verification_token", "clients", ["verification_token"])
    op.create_check_constraint(
        "ck_clients_verification_status_valid", "clients",
        "verification_status IN ('unverified', 'sent', 'under_review', 'verified', 'rejected')",
    )
    op.create_index("ix_clients_tenant_verification", "clients", ["tenant_id", "verification_status"])

    # ═══════════════════════════════════════════════════════════
    # DRIVERS: client link + DL issue date + vetting track + uniques
    # ═══════════════════════════════════════════════════════════
    op.add_column("drivers", sa.Column("client_id", sa.Integer(), nullable=True))
    op.add_column("drivers", sa.Column("dl_issued_date", sa.Date(), nullable=True))

    op.add_column("drivers", sa.Column(
        "verification_status", sa.String(length=20),
        nullable=False, server_default="unverified",
    ))
    op.add_column("drivers", sa.Column("verification_token", sa.String(length=64), nullable=True))
    op.add_column("drivers", sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("drivers", sa.Column("selfie_with_id_key", sa.String(length=255), nullable=True))
    op.add_column("drivers", sa.Column("vetted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("drivers", sa.Column("vetted_by", sa.Integer(), nullable=True))
    op.add_column("drivers", sa.Column("rejection_notes", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_drivers_client_id", "drivers", "clients",
        ["client_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_drivers_vetted_by", "drivers", "users",
        ["vetted_by"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_drivers_client_id", "drivers", ["client_id"])

    # ✅ Double-entry defense (audit confirmed 0 duplicates — safe to add)
    op.create_unique_constraint("uq_driver_tenant_phone", "drivers", ["tenant_id", "phone"])
    op.create_unique_constraint("uq_driver_tenant_id_number", "drivers", ["tenant_id", "id_number"])
    op.create_unique_constraint("uq_driver_tenant_dl_number", "drivers", ["tenant_id", "dl_number"])

    op.create_unique_constraint("uq_drivers_verification_token", "drivers", ["verification_token"])
    op.create_check_constraint(
        "ck_driver_verification_status_valid", "drivers",
        "verification_status IN ('unverified', 'sent', 'under_review', 'verified', 'rejected')",
    )
    op.create_index("ix_drivers_tenant_verification", "drivers", ["tenant_id", "verification_status"])

    # ═══════════════════════════════════════════════════════════
    # DOCUMENT REGISTRY: content-level dedupe + fraud audit trail
    # ═══════════════════════════════════════════════════════════
    op.create_table(
        "document_registry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("owner_type", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(length=30), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("file_ref", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # Mirror AuditMixin exactly as defined in app/db/database.py
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_doc_registry_owner_type_valid", "document_registry",
        "owner_type IN ('client', 'driver')",
    )
    op.create_index(
        "ix_doc_registry_tenant_hash_active", "document_registry",
        ["tenant_id", "file_hash", "is_active"],
    )
    op.create_index("ix_doc_registry_owner", "document_registry", ["owner_type", "owner_id"])
    op.create_index("ix_doc_registry_tenant", "document_registry", ["tenant_id"])


def downgrade() -> None:
    """Downgrade schema."""
    # Registry
    op.drop_index("ix_doc_registry_tenant", table_name="document_registry")
    op.drop_index("ix_doc_registry_owner", table_name="document_registry")
    op.drop_index("ix_doc_registry_tenant_hash_active", table_name="document_registry")
    op.drop_constraint("ck_doc_registry_owner_type_valid", "document_registry", type_="check")
    op.drop_table("document_registry")

    # Drivers
    op.drop_index("ix_drivers_tenant_verification", table_name="drivers")
    op.drop_constraint("ck_driver_verification_status_valid", "drivers", type_="check")
    op.drop_constraint("uq_drivers_verification_token", "drivers", type_="unique")
    op.drop_constraint("uq_driver_tenant_dl_number", "drivers", type_="unique")
    op.drop_constraint("uq_driver_tenant_id_number", "drivers", type_="unique")
    op.drop_constraint("uq_driver_tenant_phone", "drivers", type_="unique")
    op.drop_index("ix_drivers_client_id", table_name="drivers")
    op.drop_constraint("fk_drivers_vetted_by", "drivers", type_="foreignkey")
    op.drop_constraint("fk_drivers_client_id", "drivers", type_="foreignkey")
    op.drop_column("drivers", "rejection_notes")
    op.drop_column("drivers", "vetted_by")
    op.drop_column("drivers", "vetted_at")
    op.drop_column("drivers", "selfie_with_id_key")
    op.drop_column("drivers", "verification_expires_at")
    op.drop_column("drivers", "verification_token")
    op.drop_column("drivers", "verification_status")
    op.drop_column("drivers", "dl_issued_date")
    op.drop_column("drivers", "client_id")

    # Clients
    op.drop_index("ix_clients_tenant_verification", table_name="clients")
    op.drop_constraint("ck_clients_verification_status_valid", "clients", type_="check")
    op.drop_constraint("ck_clients_driving_arrangement_valid", "clients", type_="check")
    op.drop_constraint("uq_clients_verification_token", "clients", type_="unique")
    op.drop_constraint("fk_clients_vetted_by", "clients", type_="foreignkey")
    op.drop_column("clients", "rejection_notes")
    op.drop_column("clients", "vetted_by")
    op.drop_column("clients", "vetted_at")
    op.drop_column("clients", "selfie_with_id_image")
    op.drop_column("clients", "verification_expires_at")
    op.drop_column("clients", "verification_token")
    op.drop_column("clients", "verification_status")
    op.drop_column("clients", "driving_arrangement")
    op.drop_column("clients", "dl_issued_date")
    op.drop_column("clients", "last_name")
    op.drop_column("clients", "first_name")
