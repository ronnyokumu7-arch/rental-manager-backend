# app/models/payment_gateways/__init__.py

from .mpesa import MpesaConfig
from .stripe import StripeConfig
from .paypal import PaypalConfig  # ✅ FIX: Changed PayPalConfig to PaypalConfig
from .airtel import AirtelMoneyConfig
from .bank import BankAccountConfig

__all__ = [
    "MpesaConfig",
    "StripeConfig",
    "PaypalConfig",
    "AirtelConfig",
    "BankConfig",
]
