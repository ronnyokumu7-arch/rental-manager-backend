from alembic import op
import sqlalchemy as sa

revision = '60aefafa53ec'
down_revision = '45990e58dbd1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute("CREATE TYPE userrole AS ENUM ('super_admin', 'tenant_admin', 'tenant_staff')")
    op.execute("""
        ALTER TABLE users
        ALTER COLUMN role TYPE userrole
        USING role::text::userrole
    """)
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'tenant_staff'::userrole")


def downgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR USING role::text")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'tenant_staff'")
    op.execute("DROP TYPE userrole")