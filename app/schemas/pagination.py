from typing import Generic, Sequence, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


def paginate_items(items: Sequence[T], total: int | None = None, page: int = 1, page_size: int = 50) -> PaginatedResponse[T]:
    """Return a paginated response payload for a collection of items."""
    safe_page = max(page, 1)
    safe_page_size = max(page_size, 1)
    total_count = len(items) if total is None else total
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return PaginatedResponse(
        items=list(items[start:end]),
        total=total_count,
        page=safe_page,
        page_size=safe_page_size,
    )
