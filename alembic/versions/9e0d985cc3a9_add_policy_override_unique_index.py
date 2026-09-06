"""transform_policies_to_category_clause_key

Revision ID: 9e0d985cc3a9
Revises: 9e78ab2b30f4
Create Date: 2026-09-06 16:45:26.764100

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e0d985cc3a9'
down_revision: Union[str, Sequence[str], None] = '9e78ab2b30f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Transform tenant_policies from the legacy `section` enum model to the
    new `category` + `clause_key` model.

    Since this migration has NOT been deployed to production yet, we can
    reshape the table in place without needing a second follow-up revision.
    """

    # 1. Add the new columns
    op.add_column(
        "tenant_policies",
        sa.Column("category", sa.String(30), server_default="agency_policies", nullable=False),
    )
    op.add_column(
        "tenant_policies",
        sa.Column("clause_key", sa.String(60), nullable=True),
    )

    # 2. Backfill existing rows (defensive — harmless if table is empty)
    #    Old `section` enum values map to `clause_key`; 'other' becomes NULL (custom clause).
    #    All legacy rows belong to the agency_policies category.
    op.execute(
        """
        UPDATE tenant_policies
        SET category = 'agency_policies',
            clause_key = CASE
                WHEN section::text = 'other' THEN NULL
                ELSE section::text
            END
        """
    )

    # 3. Drop old indexes that reference the `section` column
    #    (defensive — drop if they exist; skip silently if missing)
    op.drop_index("ix_policies_tenant_section", table_name="tenant_policies")
    op.drop_index("ix_policies_tenant_display_order", table_name="tenant_policies")

    # 4. Drop the legacy `section` enum column entirely (unused in new model)
    op.drop_column("tenant_policies", "section")

    # 5. Create the new indexes for the category+clause_key model
    op.create_index(
        "ix_policies_tenant_category_order",
        "tenant_policies",
        ["tenant_id", "category", "display_order"],
    )
    # ✅ OVERRIDE RULE: one override per default clause per tenant.
    # Custom clauses (clause_key NULL) are exempt — unlimited per category.
    op.create_index(
        "uq_tenant_policy_clause_override",
        "tenant_policies",
        ["tenant_id", "category", "clause_key"],
        unique=True,
        postgresql_where=sa.text("clause_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Restore the legacy `section` enum column + indexes."""

    # 1. Drop new indexes
    op.drop_index("uq_tenant_policy_clause_override", table_name="tenant_policies")
    op.drop_index("ix_policies_tenant_category_order", table_name="tenant_policies")

    # 2. Re-add the legacy `section` enum column
    op.add_column(
        "tenant_policies",
        sa.Column(
            "section",
            sa.Enum(
                "rental_terms", "fuel_policy", "damage_policy",
                "late_return", "deposit", "cancellation", "other",
                name="policysection",
            ),
            nullable=True,
        ),
    )

    # 3. Backfill section from clause_key (reverse mapping)
    #    Only agency_policies rows have a meaningful reverse mapping;
    #    statutory_declaration and general_conditions rows become 'other'.
    op.execute(
        """
        UPDATE tenant_policies SET section =
            CASE
                WHEN category = 'agency_policies' AND clause_key IS NOT NULL
                    THEN clause_key::policysection
                ELSE 'other'::policysection
            END
        """
    )
    op.alter_column(
        "tenant_policies", "section",
        nullable=False, server_default="other",
    )

    # 4. Re-create legacy indexes
    op.create_index(
        "ix_policies_tenant_display_order",
        "tenant_policies",
        ["tenant_id", "display_order"],
    )
    op.create_index(
        "ix_policies_tenant_section",
        "tenant_policies",
        ["tenant_id", "section"],
    )

    # 5. Drop the new columns
    op.drop_column("tenant_policies", "clause_key")
    op.drop_column("tenant_policies", "category")
