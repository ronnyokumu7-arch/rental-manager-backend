"""fix_whillz_tenant_name_typo

Revision ID: a222d0fe0451
Revises: d61e6d9e02c1
Create Date: 2026-08-18 08:05:23.812851

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a222d0fe0451'
down_revision: Union[str, Sequence[str], None] = 'd61e6d9e02c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ✅ Typo fix: WHILLZ → WILLZ (both tables, trims any stray spaces)
    op.execute("""
        UPDATE tenants
        SET name = 'WILLZ & WHEELS CAR HIRE', updated_at = now()
        WHERE TRIM(name) ILIKE 'WHILLZ%'
    """)
    op.execute("""
        UPDATE tenant_profiles
        SET company_name = 'WILLZ & WHEELS CAR HIRE', updated_at = now()
        WHERE TRIM(company_name) ILIKE 'WHILLZ%'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE tenants
        SET name = 'WHILLZ & WHEELS CAR HIRE', updated_at = now()
        WHERE name = 'WILLZ & WHEELS CAR HIRE'
    """)
    op.execute("""
        UPDATE tenant_profiles
        SET company_name = 'WHILLZ & WHEELS CAR HIRE', updated_at = now()
        WHERE company_name = 'WILLZ & WHEELS CAR HIRE'
    """)
