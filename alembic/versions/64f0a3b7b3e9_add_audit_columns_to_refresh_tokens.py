"""add_audit_columns_to_refresh_tokens

Revision ID: 64f0a3b7b3e9
Revises: 92a70c75d07b
Create Date: 2026-08-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "64f0a3b7b3e9"
down_revision: Union[str, Sequence[str], None] = "92a70c75d07b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the audit columns expected by the current RefreshToken model."""
    op.add_column(
        "refresh_tokens",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("created_by", sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        "fk_refresh_tokens_created_by",
        "refresh_tokens",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_refresh_tokens_created_by"), "refresh_tokens", ["created_by"], unique=False)

    op.execute("UPDATE refresh_tokens SET updated_at = created_at WHERE updated_at IS NULL")


def downgrade() -> None:
    """Remove the audit columns added for refresh-token auditing."""
    op.drop_index(op.f("ix_refresh_tokens_created_by"), table_name="refresh_tokens")
    op.drop_constraint("fk_refresh_tokens_created_by", "refresh_tokens", type_="foreignkey")
    op.drop_column("refresh_tokens", "created_by")
    op.drop_column("refresh_tokens", "updated_at")
