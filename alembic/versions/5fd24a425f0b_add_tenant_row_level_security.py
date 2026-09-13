"""add tenant row level security

Revision ID: 5fd24a425f0b
Revises: 2ed6d7114c38
Create Date: 2026-09-13 16:15:56.823582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5fd24a425f0b'
down_revision: Union[str, Sequence[str], None] = '2ed6d7114c38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE FUNCTION app_current_tenant_id() RETURNS bigint
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::bigint
        $$;

        CREATE FUNCTION app_current_user_id() RETURNS bigint
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.user_id', true), '')::bigint
        $$;

        CREATE FUNCTION app_is_super_admin() RETURNS boolean
        LANGUAGE sql STABLE AS $$
            SELECT current_setting('app.is_super_admin', true) = 'true'
        $$;

        CREATE FUNCTION app_is_system() RETURNS boolean
        LANGUAGE sql STABLE AS $$
            SELECT current_setting('app.is_system', true) = 'true'
        $$;

        CREATE FUNCTION app_public_token() RETURNS text
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.public_token', true), '')
        $$;

        CREATE FUNCTION app_public_user_id() RETURNS bigint
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.public_user_id', true), '')::bigint
        $$;

        CREATE FUNCTION app_public_email() RETURNS text
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.public_email', true), '')
        $$;
        """
    )

    tenant_tables = (
        "clients",
        "vehicles",
        "bookings",
        "airport_transfers",
        "subscriptions",
        "payment_verifications",
        "invoices",
        "payments",
        "tenant_profiles",
        "tenant_policies",
        "contracts",
        "tasks",
        "activity_logs",
        "role_templates",
        "refresh_tokens",
        "mpesa_configs",
        "airtel_money_configs",
        "bank_account_configs",
        "stripe_configs",
        "paypal_configs",
        "commission_events",
        "commission_payments",
        "client_invites",
        "drivers",
    )

    for table in tenant_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                app_is_system()
                OR app_is_super_admin()
                OR tenant_id = app_current_tenant_id()
            )
            WITH CHECK (
                app_is_system()
                OR app_is_super_admin()
                OR tenant_id = app_current_tenant_id()
            )
            """
        )

    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenants")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenants
        USING (
            app_is_system()
            OR app_is_super_admin()
            OR id = app_current_tenant_id()
        )
        WITH CHECK (
            app_is_system()
            OR app_is_super_admin()
            OR id = app_current_tenant_id()
        )
        """
    )

    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON users
        USING (
            app_is_system()
            OR app_is_super_admin()
            OR id = app_current_user_id()
            OR id = app_public_user_id()
            OR email = app_public_email()
            OR tenant_id = app_current_tenant_id()
        )
        WITH CHECK (
            app_is_system()
            OR app_is_super_admin()
            OR tenant_id = app_current_tenant_id()
        )
        """
    )

    op.execute(
        """
        CREATE POLICY public_client_invite_token ON client_invites
        FOR SELECT USING (token = app_public_token())
        """
    )
    op.execute(
        """
        CREATE POLICY public_user_invite_token ON users
        FOR SELECT USING (invite_token = app_public_token())
        """
    )
    op.execute(
        """
        CREATE POLICY public_invoice_share_token ON invoices
        FOR SELECT USING (share_token = app_public_token())
        """
    )
    op.execute(
        """
        CREATE POLICY public_contract_share_token ON contracts
        FOR SELECT USING (share_token = app_public_token())
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    tables = (
        "users",
        "tenants",
        "clients",
        "vehicles",
        "bookings",
        "airport_transfers",
        "subscriptions",
        "payment_verifications",
        "invoices",
        "payments",
        "tenant_profiles",
        "tenant_policies",
        "contracts",
        "tasks",
        "activity_logs",
        "role_templates",
        "refresh_tokens",
        "mpesa_configs",
        "airtel_money_configs",
        "bank_account_configs",
        "stripe_configs",
        "paypal_configs",
        "commission_events",
        "commission_payments",
        "client_invites",
        "drivers",
    )

    for table in tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"DROP POLICY IF EXISTS public_client_invite_token ON {table}")
        op.execute(f"DROP POLICY IF EXISTS public_user_invite_token ON {table}")
        op.execute(f"DROP POLICY IF EXISTS public_invoice_share_token ON {table}")
        op.execute(f"DROP POLICY IF EXISTS public_contract_share_token ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS app_is_system()")
    op.execute("DROP FUNCTION IF EXISTS app_public_user_id()")
    op.execute("DROP FUNCTION IF EXISTS app_public_email()")
    op.execute("DROP FUNCTION IF EXISTS app_public_token()")
    op.execute("DROP FUNCTION IF EXISTS app_is_super_admin()")
    op.execute("DROP FUNCTION IF EXISTS app_current_user_id()")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant_id()")
