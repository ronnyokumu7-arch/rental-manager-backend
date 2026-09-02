"""Strict, JSON-safe serialization for values stored in Redis.

Redis must contain API-shaped data, never ``str(SQLAlchemyModel)``.  A cache
write that cannot be serialized is skipped by its caller; serving a corrupt
cache value is worse than serving an uncached response.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
import json

from pydantic import BaseModel


_SCALAR_TYPES = (str, int, float, bool, type(None), date, datetime, Decimal, Enum)


def serialize_cache_item(item: Any) -> Any:
    """Convert a Pydantic model, mapping, or loaded ORM object to JSON-safe data.

    Only already-loaded SQLAlchemy attributes are traversed.  This prevents
    accidental async lazy loads while retaining response fields such as a
    contract's booking/client details.
    """
    return _serialize(item, seen=set())


def deserialize_cache_list(payload: str) -> list[dict[str, Any]]:
    """Load a list cache payload, rejecting legacy stringified ORM entries."""
    data = json.loads(payload)
    if not isinstance(data, list) or any(not isinstance(item, Mapping) for item in data):
        raise ValueError("Cache payload is not a list of objects")
    return data


def _serialize(value: Any, seen: set[int]) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, _SCALAR_TYPES):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        return value
    if isinstance(value, Mapping):
        return {str(key): _serialize(item, seen) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(item, seen) for item in value]

    if hasattr(value, "__table__"):
        identity = id(value)
        if identity in seen:
            return None
        seen.add(identity)
        try:
            columns = {column.key for column in value.__table__.columns}
            data = {
                column.key: _serialize(getattr(value, column.key, None), seen)
                for column in value.__table__.columns
            }
            # Relationships explicitly eager-loaded by the endpoint are present
            # in __dict__.  Do not access attributes that are not already loaded.
            for key, item in value.__dict__.items():
                if not key.startswith("_") and key not in columns:
                    data[key] = _serialize(item, seen)
            return data
        finally:
            seen.remove(identity)

    raise TypeError(f"Unsupported Redis cache value: {type(value).__name__}")
