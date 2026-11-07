from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.task import TaskPriority
from app.services.task_core import TaskCoreService


@pytest.mark.asyncio
async def test_system_generated_task_creation_is_disabled():
    db = AsyncMock()
    result = await TaskCoreService.smart_create_task(
        db=db,
        tenant_id=1,
        title="Automatic task",
        description="This task must not be created.",
        category="operations",
        priority=TaskPriority.high,
        due_date=datetime.now(),
        target_type="client",
        target_id=1,
        is_system_generated=True,
    )

    assert result is None
    db.execute.assert_not_awaited()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_task_creation_remains_available(monkeypatch):
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    task = SimpleNamespace(is_system_generated=False, user_id=7)
    monkeypatch.setattr("app.services.task_core.Task", lambda **kwargs: task)

    result = await TaskCoreService.smart_create_task(
        db=db,
        tenant_id=1,
        title="Manual task",
        description="This task was requested by a user.",
        category="operations",
        priority=TaskPriority.high,
        due_date=datetime.now(),
        target_type="client",
        target_id=1,
        assignee_id=7,
        is_system_generated=False,
    )

    assert result is task
    db.add.assert_called_once_with(task)
    assert result.is_system_generated is False
    assert result.user_id == 7
    db.execute.assert_not_awaited()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(result)
