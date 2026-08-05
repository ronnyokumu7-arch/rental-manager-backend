from app.schemas.pagination import PaginatedResponse, paginate_cached_items


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
