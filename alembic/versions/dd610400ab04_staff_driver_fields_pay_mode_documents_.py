"""staff driver fields: pay_mode, documents, required compliance

Revision ID: dd610400ab04
Revises: d5e6f7a8b9c0
Create Date: 2026-08-22 08:57:47.649928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd610400ab04'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('drivers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('profile_photo_key', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('id_front_key', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('id_back_key', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('dl_photo_key', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('pay_mode', sa.String(length=20), nullable=False))
        batch_op.alter_column('id_number',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
        batch_op.alter_column('dl_number',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
        # ✅ Autogenerate misses check constraints on existing tables — added manually
        batch_op.create_check_constraint(
            constraint_name="ck_driver_pay_mode_valid",
            condition="pay_mode IN ('commission', 'fixed_per_job', 'payroll')",
        )
        batch_op.create_check_constraint(
            constraint_name="ck_driver_employment_type_valid",
            condition="employment_type IN ('in_house', 'contracted')",
        )
        batch_op.create_check_constraint(
            constraint_name="ck_driver_status_valid",
            condition="status IN ('available', 'on_trip', 'on_leave', 'suspended')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('drivers', schema=None) as batch_op:
        batch_op.drop_constraint("ck_driver_status_valid", type_="check")
        batch_op.drop_constraint("ck_driver_employment_type_valid", type_="check")
        batch_op.drop_constraint("ck_driver_pay_mode_valid", type_="check")
        batch_op.alter_column('dl_number',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
        batch_op.alter_column('id_number',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
        batch_op.drop_column('pay_mode')
        batch_op.drop_column('dl_photo_key')
        batch_op.drop_column('id_back_key')
        batch_op.drop_column('id_front_key')
        batch_op.drop_column('profile_photo_key')
