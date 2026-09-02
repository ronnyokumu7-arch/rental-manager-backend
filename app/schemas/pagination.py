from typing import Any, Generic, Sequence, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


def _orm_to_dict(obj: Any) -> Any:
    """Convert loaded ORM state without triggering async lazy-loads."""
    if hasattr(obj, "__table__"):
        columns = {column.key for column in obj.__table__.columns}
        data = {column.key: getattr(obj, column.key, None) for column in obj.__table__.columns}
        data.update({
            key: value
            for key, value in obj.__dict__.items()
            if not key.startswith("_") and key not in columns
        })
        return data
    return obj


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)

    model_config = {"from_attributes": True}


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
        items=[_orm_to_dict(i) for i in items[start:end]],
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
