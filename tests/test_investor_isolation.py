from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from unittest.mock import AsyncMock, MagicMock

from app.dependencies.tenant import reject_investor_tenant_access
from app.models.users import UserRole
from app.models.vehicles import Vehicle
from app.routers.vehicle._helpers import get_authorized_vehicle_async


def test_investor_is_denied_tenant_data_access():
    investor = SimpleNamespace(role=UserRole.investor)

    with pytest.raises(HTTPException) as exc:
        reject_investor_tenant_access(investor)

    assert exc.value.status_code == 403


def test_tenant_user_can_access_tenant_data():
    tenant_admin = SimpleNamespace(role=UserRole.tenant_admin)

    reject_investor_tenant_access(tenant_admin)


@pytest.mark.asyncio
async def test_investor_vehicle_lookup_filters_by_owner_and_tenant():
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    db = AsyncMock()
    db.execute.return_value = result
    investor = SimpleNamespace(role=UserRole.investor, id=17, tenant_id=4)

    with pytest.raises(HTTPException) as exc:
        await get_authorized_vehicle_async(22, investor, db)

    assert exc.value.status_code == 404
    stmt = db.execute.await_args.args[0]
    compiled_sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "vehicles.owner_id = 17" in compiled_sql
    assert "vehicles.tenant_id = 4" in compiled_sql