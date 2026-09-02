from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest
from pydantic import BaseModel

from app.schemas.pagination import PaginatedResponse, paginate_cached_items
from app.services.cache.serialization import deserialize_cache_list, serialize_cache_item


def test_paginate_cached_items_wraps_plain_list_in_paginated_response():
    items = [{"id": 1}, {"id": 2}]

    response = paginate_cached_items(items, page=2, page_size=1)

    assert isinstance(response, PaginatedResponse)
    assert response.items == [{"id": 2}]
    assert response.total == 2
    assert response.page == 2
    assert response.page_size == 1


def test_paginate_cached_items_returns_existing_paginated_response():
    existing = PaginatedResponse(items=[{"id": 1}], total=1, page=1, page_size=10)

    response = paginate_cached_items(existing, page=3, page_size=20)

    assert response is existing


class _Column:
    def __init__(self, key):
        self.key = key


class _Table:
    columns = [_Column("id"), _Column("amount"), _Column("created_at")]


class _OrmLike:
    __table__ = _Table()

    def __init__(self):
        self.id = 4
        self.amount = Decimal("1500.00")
        self.created_at = datetime(2026, 9, 2, tzinfo=timezone.utc)
        self.client = {"id": 8, "full_name": "Amina"}


class _Payload(BaseModel):
    id: int
    when: datetime


def test_cache_serializer_preserves_orm_data_as_json_safe_dict():
    payload = serialize_cache_item(_OrmLike())

    assert payload == {
        "id": 4,
        "amount": "1500.00",
        "created_at": "2026-09-02T00:00:00+00:00",
        "client": {"id": 8, "full_name": "Amina"},
    }
    assert json.loads(json.dumps(payload)) == payload


def test_cache_serializer_supports_pydantic_models_and_rejects_unknown_objects():
    assert serialize_cache_item(_Payload(id=1, when=datetime(2026, 9, 2))) == {
        "id": 1,
        "when": "2026-09-02T00:00:00",
    }

    with pytest.raises(TypeError, match="Unsupported Redis cache value"):
        serialize_cache_item(object())


def test_legacy_stringified_orm_cache_is_rejected():
    with pytest.raises(ValueError, match="list of objects"):
        deserialize_cache_list('["<app.models.clients.Client object at 0x1>"]')
