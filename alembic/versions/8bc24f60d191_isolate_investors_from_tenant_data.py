"""isolate investors from tenant data

Revision ID: 8bc24f60d191
Revises: 06055391511c
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op


revision: str = "8bc24f60d191"
down_revision: Union[str, Sequence[str], None] = "06055391511c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = (
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


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app_is_investor() RETURNS boolean
        LANGUAGE sql STABLE AS $$
            SELECT COALESCE(current_setting('app.is_investor', true) = 'true', false)
        $$;
        """
    )

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        if table == "vehicles":
            access_policy = """
                app_is_system()
                OR app_is_super_admin()
                OR (
                    NOT app_is_investor()
                    AND tenant_id = app_current_tenant_id()
                )
                OR (
                    app_is_investor()
                    AND tenant_id = app_current_tenant_id()
                    AND owner_id = app_current_user_id()
                )
            """
        else:
            access_policy = """
                app_is_system()
                OR app_is_super_admin()
                OR (
                    NOT app_is_investor()
                    AND tenant_id = app_current_tenant_id()
                )
            """
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING ({access_policy})
            WITH CHECK ({access_policy})
            """
        )

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenants")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenants
        USING (
            app_is_system()
            OR app_is_super_admin()
            OR (NOT app_is_investor() AND id = app_current_tenant_id())
        )
        WITH CHECK (
            app_is_system()
            OR app_is_super_admin()
            OR (NOT app_is_investor() AND id = app_current_tenant_id())
        )
        """
    )

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
            OR (
                NOT app_is_investor()
                AND tenant_id = app_current_tenant_id()
            )
        )
        WITH CHECK (
            app_is_system()
            OR app_is_super_admin()
            OR (
                NOT app_is_investor()
                AND tenant_id = app_current_tenant_id()
            )
            OR (
                app_is_investor()
                AND id = app_current_user_id()
                AND tenant_id = app_current_tenant_id()
            )
        )
        """
    )

    op.execute("ALTER TABLE investor_leases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE investor_leases FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS investor_lease_isolation ON investor_leases")
    op.execute(
        """
        CREATE POLICY investor_lease_isolation ON investor_leases
        USING (
            app_is_system()
            OR app_is_super_admin()
            OR (
                NOT app_is_investor()
                AND tenant_id = app_current_tenant_id()
            )
            OR (
                app_is_investor()
                AND tenant_id = app_current_tenant_id()
                AND investor_id = app_current_user_id()
            )
        )
        WITH CHECK (
            app_is_system()
            OR app_is_super_admin()
            OR (
                NOT app_is_investor()
                AND tenant_id = app_current_tenant_id()
            )
            OR (
                app_is_investor()
                AND tenant_id = app_current_tenant_id()
                AND investor_id = app_current_user_id()
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS investor_lease_isolation ON investor_leases")
    op.execute("ALTER TABLE investor_leases NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE investor_leases DISABLE ROW LEVEL SECURITY")

    for table in TENANT_TABLES:
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
    op.execute("DROP FUNCTION IF EXISTS app_is_investor()")