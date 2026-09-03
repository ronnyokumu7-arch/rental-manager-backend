# app/core/timeutils.py
"""
✅ PLATFORM DATETIME CONTRACT — single source of truth for time.

Rules:
  - All math happens in aware UTC. No naive comparisons, ever.
  - Naive input is interpreted as platform time (Africa/Nairobi), explicitly.
  - Responses serialize as platform-time ISO with offset (e.g. +03:00),
    so frontends render exact local times with zero tz math.
  - Defaults: pickup = now; return = pickup + 1 day (exactly 1 billable day).
  - "Now" is allowed; only strictly-past (beyond a 2-min skew grace) is blocked.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

PLATFORM_TZ = ZoneInfo("Africa/Nairobi")
UTC = timezone.utc

# Tolerance for client/server clock skew. "Now" (and up to 2 min before) is valid.
PAST_GRACE = timedelta(minutes=2)


# ---------------------------------------------------------------------------
# NOW
# ---------------------------------------------------------------------------
def now_utc() -> datetime:
    """Current instant, aware UTC. The ONLY 'now' the platform uses."""
    return datetime.now(UTC)


def now_platform() -> datetime:
    """Current instant in platform time (for display/defaulting UI)."""
    return datetime.now(PLATFORM_TZ)


# ---------------------------------------------------------------------------
# PARSE / NORMALIZE / SERIALIZE
# ---------------------------------------------------------------------------
def normalize(dt: datetime) -> datetime:
    """
    Aware-UTC canonical form.
    Naive → interpreted as platform time (Africa/Nairobi).
    Aware → same instant, converted to UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PLATFORM_TZ)
    return dt.astimezone(UTC)


def parse_datetime(value, *, field_name: str = "datetime") -> datetime:
    """
    Accept datetime instance or ISO-8601 string ('Z' or '+03:00' both fine).
    Returns aware UTC. Raises ValueError with a human-readable message.
    """
    if isinstance(value, datetime):
        return normalize(value)

    if isinstance(value, str):
        text = value.strip()
        try:
            return normalize(datetime.fromisoformat(text))  # py3.11 handles 'Z'
        except ValueError:
            raise ValueError(
                f"{field_name}: invalid ISO-8601 datetime '{text}'. "
                "Expected e.g. 2026-09-03T07:30:00+03:00"
            )

    raise ValueError(f"{field_name}: expected ISO-8601 string or datetime, got {type(value).__name__}")


def to_platform_iso(dt: datetime) -> str:
    """Serialize for API responses: platform time with offset. Never date-only."""
    return dt.astimezone(PLATFORM_TZ).isoformat()


# ---------------------------------------------------------------------------
# DEFAULTS
# ---------------------------------------------------------------------------
def default_pickup() -> datetime:
    """Pickup defaults to today-and-now, rounded down to the current minute."""
    return now_utc().replace(second=0, microsecond=0)


def default_return(pickup: datetime) -> datetime:
    """Return defaults to pickup + 1 day (same time) → exactly 1 billable day."""
    return pickup + timedelta(days=1)


def add_days(dt: datetime, days: int) -> datetime:
    """Whole-day shift for extensions/reductions (keeps time-of-day exact)."""
    return dt + timedelta(days=days)


def resolve_schedule(
    pickup_raw: Optional[object],
    return_raw: Optional[object],
) -> Tuple[datetime, datetime]:
    """
    Apply precedence + defaults:
      pickup = provided or now;  return = provided or pickup + 1 day.
    Returns (pickup_utc, return_utc), both aware.
    """
    pickup = parse_datetime(pickup_raw, field_name="pickup_at") if pickup_raw else default_pickup()
    ret = (
        parse_datetime(return_raw, field_name="scheduled_return_at")
        if return_raw
        else default_return(pickup)
    )
    return pickup, ret


# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------
def validate_new_schedule(pickup: datetime, return_at: datetime) -> None:
    """
    New bookings: block strictly-past pickups (2-min grace), require return > pickup.
    Raises ValueError (mapped to 422 by callers).
    """
    if pickup < now_utc() - PAST_GRACE:
        raise ValueError("Pickup time cannot be in the past. Please select now or a future date and time.")
    if return_at <= pickup:
        raise ValueError("Return must be strictly after pickup.")


def validate_order(pickup: datetime, return_at: datetime) -> None:
    """Order-only check (used by change flows where pickup may be historical)."""
    if return_at <= pickup:
        raise ValueError("Return must be strictly after pickup (minimum 1 day).")
