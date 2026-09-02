# app/schemas/pagination.py
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, Sequence, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


_SCALARS = (str, int, float, bool, bytes, type(None), datetime, date, Decimal, Enum)


def _normalize_item(item: Any) -> Any:
    """
    ✅ Deterministic response payloads: convert SQLAlchemy ORM instances
    (including already-loaded relationships) into plain dicts so response
    validation never depends on Pydantic's from_attributes behavior.
    Dicts, Pydantic models, and scalar values pass through untouched.
    Only touches __dict__ (loaded state) — never triggers lazy loading.
    """
    if isinstance(item, (dict, BaseModel)) or isinstance(item, _SCALARS):
        return item
    if isinstance(item, (list, tuple, set)):
        return [_normalize_item(v) for v in item]
    if hasattr(item, "__table__"):  # SQLAlchemy ORM instance
        data = {
            col.key: _normalize_item(getattr(item, col.key, None))
            for col in obj_columns(item)
        }
        for key, value in list(item.__dict__.items()):
            if key.startswith("_") or key in data:
                continue
            data[key] = _normalize_item(value)
        return data
    return item


def obj_columns(item: Any):
    return item.__table__.columns


def paginate_items(
    items: Sequence[T] | PaginatedResponse[T],
    total: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[T]:
    """Return a paginated response payload for a collection of items."""
    if isinstance(items, PaginatedResponse):
        return items

    safe_page = max(page, 1)
    safe_page_size = max(page_size, 1)
    total_count = len(items) if total is None else total
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return PaginatedResponse(
        items=[_normalize_item(i) for i in items[start:end]],
        total=total_count,
        page=safe_page,
        page_size=safe_page_size,
    )


def paginate_cached_items(
    items: Sequence[T] | PaginatedResponse[T],
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[T]:
    """Normalize cached list payloads to the shared paginated response envelope."""
    if isinstance(items, PaginatedResponse):
        return items

    return paginate_items(items, total=len(items), page=page, page_size=page_size)
