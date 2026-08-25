# app/services/mpesa.py
"""
M-Pesa (Daraja) integration service — SANDBOX first.

1. OAuth access token (client_credentials)
2. Lipa na M-Pesa Express (STK Push) — the "Pay" prompt on invoices

Production switch = env vars ONLY (MPESA_BASE_URL / SHORTCODE / PASSKEY).
"""
import base64
import logging
from datetime import datetime

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

TIMEOUT = 30.0  # sandbox can be slow


class MpesaError(Exception):
    """Raised when Daraja returns an error payload."""


async def get_access_token() -> str:
    """OAuth client-credentials flow. Proves consumer key + secret work."""
    url = f"{settings.mpesa_base_url}/oauth/v1/generate?grant_type=client_credentials"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(
            url,
            auth=(settings.mpesa_consumer_key, settings.mpesa_consumer_secret),
        )
    if resp.status_code != 200:
        logger.error("M-Pesa OAuth failed: %s %s", resp.status_code, resp.text)
        raise MpesaError(f"OAuth failed ({resp.status_code})")
    token = resp.json().get("access_token")
    if not token:
        raise MpesaError("OAuth response missing access_token")
    return token


def _stk_password(timestamp: str) -> str:
    """Password = base64(Shortcode + Passkey + Timestamp) — per Daraja docs."""
    raw = f"{settings.mpesa_shortcode}{settings.mpesa_passkey}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


async def stk_push(
    phone_number: str,
    amount: float,
    account_reference: str,
    description: str = "Rent payment",
) -> dict:
    """Sends the STK prompt to the client's phone. Returns Daraja acknowledgement."""
    token = await get_access_token()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    payload = {
        "BusinessShortCode": settings.mpesa_shortcode,
        "Password": _stk_password(timestamp),
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(round(amount)),
        "PartyA": phone_number,
        "PartyB": settings.mpesa_shortcode,
        "PhoneNumber": phone_number,
        "CallBackURL": settings.mpesa_callback_url,
        "AccountReference": account_reference[:12],   # Daraja max 12 chars
        "TransactionDesc": description[:13],          # Daraja max 13 chars
    }

    url = f"{settings.mpesa_base_url}/mpesa/stkpush/v1/processrequest"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    data = resp.json()
    if resp.status_code != 200 or str(data.get("ResponseCode", "")) != "0":
        logger.error("STK Push failed: %s", data)
        raise MpesaError(
            data.get("errorMessage") or data.get("ResponseDescription") or "STK Push failed"
        )
    return data
