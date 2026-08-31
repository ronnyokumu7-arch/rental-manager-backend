import asyncio
import logging
from typing import List
import resend

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize Resend
resend.api_key = settings.resend_api_key

async def _send(to: str | List[str], subject: str, html: str) -> bool:
    """
    Sends an email using Resend.
    Uses asyncio.to_thread to prevent blocking the FastAPI event loop.
    """
    try:
        await asyncio.to_thread(
            resend.Emails.send,
            {
                "from": f"{settings.from_name} <{settings.from_email}>",
                "to": to if isinstance(to, list) else [to],
                "subject": subject,
                "html": html,
            }
        )
        return True
    except Exception as e:
        logger.error(f"Email send failed to {to}: {e}")
        return False
