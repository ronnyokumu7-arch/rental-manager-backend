from types import SimpleNamespace

import pytest
from fastapi import Request

from app.models.users import UserRole
from app.routers.activity_logs import get_activity_logs


class RecordingResult:
    def scalar(self):
        return 0

    def scalars(self):
        return self

    def all(self):
        return []


class RecordingSession:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return RecordingResult()


@pytest.mark.asyncio
async def test_recent_activity_feed_is_limited_and_tenant_scoped():
    db = RecordingSession()
    request = Request(
        {"type": "http", "method": "GET", "path": "/activity-logs/", "headers": []}
    )

    await get_activity_logs.__wrapped__(
        request=request,
        user_id=None,
        action=None,
        recent_activity_only=True,
        target_type=None,
        start_date=None,
        end_date=None,
        sort_by_priority=False,
        page=1,
        page_size=50,
        db=db,
        current_user=SimpleNamespace(role=UserRole.tenant_staff, tenant_id=7),
    )

    assert len(db.statements) == 2
    for statement in db.statements:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "activity_logs.tenant_id = 7" in sql
        assert (
            "activity_logs.action IN "
            "('payment_received', 'contract_sent', 'contract_signed')"
        ) in sql


@pytest.mark.asyncio
async def test_full_activity_audit_feed_remains_available_when_not_filtered():
    db = RecordingSession()
    request = Request(
        {"type": "http", "method": "GET", "path": "/activity-logs/", "headers": []}
    )

    await get_activity_logs.__wrapped__(
        request=request,
        user_id=None,
        action=None,
        recent_activity_only=False,
        target_type=None,
        start_date=None,
        end_date=None,
        sort_by_priority=False,
        page=1,
        page_size=50,
        db=db,
        current_user=SimpleNamespace(role=UserRole.tenant_staff, tenant_id=7),
    )

    assert len(db.statements) == 2
    for statement in db.statements:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "activity_logs.tenant_id = 7" in sql
        assert "activity_logs.action IN" not in sql
