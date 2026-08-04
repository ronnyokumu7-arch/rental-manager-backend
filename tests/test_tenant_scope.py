from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.dependencies.tenant import resolve_tenant_scope
from app.models.users import UserRole


def user(role: UserRole, tenant_id: int | None = None):
    return SimpleNamespace(role=role, tenant_id=tenant_id)


def test_tenant_member_is_always_scoped_to_own_tenant():
    scope = resolve_tenant_scope(user(UserRole.tenant_staff, 7))

    assert scope.tenant_id == 7
    assert scope.is_system_scope is False


def test_tenant_member_cannot_request_another_tenant():
    with pytest.raises(HTTPException) as exc:
        resolve_tenant_scope(user(UserRole.tenant_admin, 7), requested_tenant_id=8)

    assert exc.value.status_code == 403


def test_super_admin_can_use_system_scope_or_select_a_tenant():
    system_scope = resolve_tenant_scope(user(UserRole.super_admin))
    selected_scope = resolve_tenant_scope(user(UserRole.super_admin), requested_tenant_id=9)

    assert system_scope.tenant_id is None
    assert system_scope.is_system_scope is True
    assert selected_scope.tenant_id == 9
    assert selected_scope.is_system_scope is False


def test_orphaned_non_system_user_is_denied():
    with pytest.raises(HTTPException) as exc:
        resolve_tenant_scope(user(UserRole.tenant_staff))

    assert exc.value.status_code == 403
