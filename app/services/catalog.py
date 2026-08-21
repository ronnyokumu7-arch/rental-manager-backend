# app/services/catalog.py
"""
Service Catalog — single source of truth for rental services.

Consumers: pricing engine, bookings router, duty scheduler, invoicing, frontend.

Design principles:
  * Definitions are CODE (versioned, testable). Rates are DATA (tenant config).
  * billing_model selects a pricing STRATEGY over a shared rate card.
  * Alias map keeps historical service_type values resolvable after renames.
  * rate_extras (JSONB on the config row) feeds model-specific rates,
    so new pricing models ship WITHOUT schema migrations.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


class BillingModel(str, enum.Enum):
    rolling_24h = "rolling_24h"   # 24h countdown from pickup (selfdrive, pro_driver)
    event_base = "event_base"     # flat base hours + hourly add-ons (wedding)
    hourly = "hourly"             # rate × hours, min charge (short chauffeur, corporate)
    package = "package"           # half-day / full-day blocks + extra hours (excursions)
    fixed_route = "fixed_route"   # flat per standard route (JKIA → hotel)
    distance_time = "distance_time"  # base fare + $/km + $/time (taxi, custom transfers)
    route_stops = "route_stops"   # priced per place visited (future)


class ServiceCategory(str, enum.Enum):
    selfdrive = "selfdrive"
    chauffeur = "chauffeur"
    transfer = "transfer"
    event = "event"


@dataclass(frozen=True)
class ServiceDefinition:
    key: str
    display_name: str
    category: ServiceCategory
    billing_model: BillingModel   # default; tenant config may override
    base_hours: int               # 24 / 12 / 0
    requires_driver: bool
    is_live: bool
    description: str


# Known rate_extras keys (validation + documentation; strategies read what they need)
KNOWN_RATE_EXTRA_KEYS = {
    "per_hour", "per_km", "per_min", "base_fare", "fixed_rate",
    "half_day_rate", "half_day_hours", "full_day_rate", "full_day_hours",
    "min_charge_hours", "route_rates", "per_stop_rate",
}


SERVICE_CATALOG: Dict[str, ServiceDefinition] = {
    "selfdrive": ServiceDefinition(
        "selfdrive", "Self Drive", ServiceCategory.selfdrive,
        BillingModel.rolling_24h, 24, False, True,
        "24h rolling clock from pickup — 1h grace, then hourly overtime.",
    ),
    "chauffeur_pro_driver": ServiceDefinition(
        "chauffeur_pro_driver", "Chauffeur · Pro Driver", ServiceCategory.chauffeur,
        BillingModel.rolling_24h, 24, True, True,
        "Multi-day trips with driver — selfdrive rates + driver fee stack.",
    ),
    "chauffeur_wedding": ServiceDefinition(
        "chauffeur_wedding", "Chauffeur · Wedding", ServiceCategory.event,
        BillingModel.event_base, 12, True, True,
        "Single-event 12h base package + hourly add-ons.",
    ),
    # ── PARKED: defined now, activated with their pricing models ──
    "chauffeur_hourly": ServiceDefinition(
        "chauffeur_hourly", "Chauffeur · Hourly", ServiceCategory.chauffeur,
        BillingModel.hourly, 0, True, False,
        "Short chauffeur jobs billed per hour (min charge applies).",
    ),
    "corporate": ServiceDefinition(
        "corporate", "Corporate Transport", ServiceCategory.chauffeur,
        BillingModel.hourly, 0, True, False,
        "Contract corporate transportation, billed per hour.",
    ),
    "city_excursion": ServiceDefinition(
        "city_excursion", "City Excursion", ServiceCategory.transfer,
        BillingModel.package, 0, True, False,
        "Half-day (1–4h) or full-day (8h + hourly add-ons) touring.",
    ),
    "airport_transfer": ServiceDefinition(
        "airport_transfer", "Airport Transfer", ServiceCategory.transfer,
        BillingModel.fixed_route, 0, True, False,
        "Flat rate per standard route (e.g. JKIA → CBD).",
    ),
    "chauffeur_taxi": ServiceDefinition(
        "chauffeur_taxi", "Taxi", ServiceCategory.transfer,
        BillingModel.distance_time, 0, True, False,
        "Metered: base fare + per-km + per-minute.",
    ),
    "route_stops_service": ServiceDefinition(
        "route_stops_service", "Places-Visited Tour", ServiceCategory.transfer,
        BillingModel.route_stops, 0, True, False,
        "Priced per place visited (future).",
    ),
}

# ✅ Backward compatibility: historical values resolve to current keys.
SERVICE_ALIASES: Dict[str, str] = {
    "with_driver": "chauffeur_pro_driver",
    "wedding": "chauffeur_wedding",
}


def resolve_key(service_type: Optional[str]) -> str:
    if not service_type:
        return "selfdrive"
    return SERVICE_ALIASES.get(service_type, service_type)


def get_service(service_type: Optional[str]) -> ServiceDefinition:
    return SERVICE_CATALOG.get(resolve_key(service_type), SERVICE_CATALOG["selfdrive"])


def live_services() -> List[ServiceDefinition]:
    return [s for s in SERVICE_CATALOG.values() if s.is_live]


def services_by_category(category: ServiceCategory) -> List[ServiceDefinition]:
    return [s for s in SERVICE_CATALOG.values() if s.category == category and s.is_live]


def to_dict(service: ServiceDefinition) -> dict:
    d = asdict(service)
    d["category"] = service.category.value
    d["billing_model"] = service.billing_model.value
    return d
