"""
Cache orchestrator. Re-exports all caching functions for easy importing.
Usage: from app.services.cache import invalidate_booking_cache, get_cached_vehicle_list, etc.
"""
from .subscription import (
    get_cached_subscription_status, set_cached_subscription_status,
    get_cached_subscription_warning, set_cached_subscription_warning,
    invalidate_subscription_cache
)
from .vehicle import get_cached_vehicle_list, set_cached_vehicle_list, invalidate_vehicle_cache
from .client import get_cached_client_list, set_cached_client_list, invalidate_client_cache
from .contract import get_cached_contract_list, set_cached_contract_list, invalidate_contract_cache
from .invoice import get_cached_invoice_list, set_cached_invoice_list, invalidate_invoice_cache
from .payment import get_cached_payment_list, set_cached_payment_list, invalidate_payment_cache
from .activity_log import get_cached_activity_logs, set_cached_activity_logs, invalidate_activity_log_cache
from .booking import get_cached_booking_list, set_cached_booking_list, invalidate_booking_cache
from .tenant import get_cached_tenant_list, set_cached_tenant_list, invalidate_tenant_cache
from .task import get_cached_task_list, set_cached_task_list, invalidate_task_cache
from .user import get_cached_user_list, set_cached_user_list, invalidate_user_cache

__all__ = [
    "get_cached_subscription_status", "set_cached_subscription_status",
    "get_cached_subscription_warning", "set_cached_subscription_warning",
    "invalidate_subscription_cache",
    "get_cached_vehicle_list", "set_cached_vehicle_list", "invalidate_vehicle_cache",
    "get_cached_client_list", "set_cached_client_list", "invalidate_client_cache",
    "get_cached_contract_list", "set_cached_contract_list", "invalidate_contract_cache",
    "get_cached_invoice_list", "set_cached_invoice_list", "invalidate_invoice_cache",
    "get_cached_payment_list", "set_cached_payment_list", "invalidate_payment_cache",
    "get_cached_activity_logs", "set_cached_activity_logs", "invalidate_activity_log_cache",
    "get_cached_booking_list", "set_cached_booking_list", "invalidate_booking_cache",
    "get_cached_tenant_list", "set_cached_tenant_list", "invalidate_tenant_cache",
    "get_cached_task_list", "set_cached_task_list", "invalidate_task_cache",
    "get_cached_user_list", "set_cached_user_list", "invalidate_user_cache",
]
