# app/services/contract_pdf.py

import os
import base64
import asyncio
import urllib.request
from typing import Optional
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.contracts import Contract
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.vehicles import Vehicle
from app.models.tenants import Tenant
from app.models.tenant_profile import TenantProfile
from app.services.browser_pool import browser_pool
from app.services.storage import get_backend

BASE_DIR = Path(__file__).resolve().parent.parent
template_env = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(['html', 'xml'])
)


async def resolve_signature_data_uri(contract: Contract) -> Optional[str]:
    """
    ✅ BULLETPROOF SIGNATURE RESOLVER (backend-aware)
    The sign endpoint stores whatever upload_file() returns, i.e. an
    authenticated API URL: {api_base}/api/v1/files/tenant_{id}/{category}/{uuid}.png

    Resolution order:
      1. API files URL → Cloudinary: backend.signed_url() then fetch bytes
                         Local disk: read uploads_dir/{relative_path} directly
      2. Direct http(s) URL (raw Cloudinary secure_url) → fetch bytes
      3. Data URI stored directly → return as-is
      4. Legacy local file path   → read from disk if it still exists
    Returns None if nothing is available (template falls back to typed /s/ name).
    """
    ref = getattr(contract, "signature_image_path", None)
    if not ref:
        return None

    loop = asyncio.get_running_loop()

    def _fetch(url: str) -> Optional[bytes]:
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return resp.read()
        except Exception as e:
            print(f"❌ Failed to fetch signature bytes: {e}")
            return None

    def _to_data_uri(data: bytes) -> str:
        return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")

    # 1. ✅ Authenticated API URL produced by upload_file()
    api_base = get_settings().public_url_base.rstrip("/")
    files_prefix = f"{api_base}/api/v1/files/"
    if ref.startswith(files_prefix):
        relative_path = ref[len(files_prefix):].lstrip("/")

        # a) Cloudinary backend → short-lived signed URL → fetch bytes
        backend = get_backend()
        signed = backend.signed_url(relative_path, ttl_seconds=300)
        if signed:
            data = await loop.run_in_executor(None, _fetch, signed)
            if data:
                return _to_data_uri(data)

        # b) Local backend (or signed_url failure) → read from disk
        upload_dir = Path(get_settings().uploads_dir).resolve()
        local_path = (upload_dir / relative_path).resolve()
        try:
            local_path.relative_to(upload_dir)  # safety: no path traversal
            if local_path.exists() and local_path.is_file():
                with open(local_path, "rb") as f:
                    return _to_data_uri(f.read())
        except ValueError:
            pass

        print(f"⚠️ Could not resolve signature via storage backend: {ref}")
        return None

    # 2. Direct Cloudinary / public http(s) URL
    if ref.startswith("http://") or ref.startswith("https://"):
        data = await loop.run_in_executor(None, _fetch, ref)
        if data:
            return _to_data_uri(data)
        return None

    # 3. Data URI stored directly in the column
    if ref.startswith("data:"):
        return ref

    # 4. Legacy local file path (ephemeral — does not survive Render deploys)
    if os.path.exists(ref):
        try:
            with open(ref, "rb") as img_file:
                return _to_data_uri(img_file.read())
        except Exception as e:
            print(f"❌ Error encoding local signature: {e}")
            return None

    print(f"⚠️ Signature reference unusable: {ref}")
    return None


async def generate_contract_pdf(contract: Contract, db: AsyncSession) -> bytes:
    # 1. ASYNC DATA FETCHING
    booking_stmt = select(Booking).where(Booking.id == contract.booking_id)
    booking = (await db.execute(booking_stmt)).scalars().first()

    client = None
    vehicle = None
    if booking:
        if booking.client_id:
            client_stmt = select(Client).where(Client.id == booking.client_id)
            client = (await db.execute(client_stmt)).scalars().first()

        if booking.vehicle_id:
            vehicle_stmt = select(Vehicle).where(Vehicle.id == booking.vehicle_id)
            vehicle = (await db.execute(vehicle_stmt)).scalars().first()

    tenant_stmt = select(Tenant).where(Tenant.id == contract.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()

    # ✅ FETCH TENANT PROFILE FOR RICH DETAILS
    tenant_profile = None
    if tenant:
        profile_stmt = select(TenantProfile).where(TenantProfile.tenant_id == tenant.id)
        tenant_profile = (await db.execute(profile_stmt)).scalars().first()

    # 2. ✅ SIGNATURE: resolve via storage service (survives deploys)
    signature_data_uri = None
    if contract.signed_by_client:
        signature_data_uri = await resolve_signature_data_uri(contract)

    default_policies = [
        "FUEL POLICY: Vehicle must be returned with the same fuel level as at pickup. Standard refueling fee applies if returned below level.",
        "MILEAGE LIMITS: Daily cap is 550 KM. Excess mileage is billed at KES 50/KM.",
        "LATE RETURNS: Returns over 2 hours late are treated as a new rental day (daily rates apply)."
    ]

    # ✅ FIXED: Priority order for daily rate:
    # 1. booking.daily_rate (admin-set override via invoice modal) — WINS if set
    # 2. vehicle.daily_rate (vehicle's standard rate) — fallback
    # 3. Derived from booking.total_amount — last-resort
    # Rental days are inclusive of pickup AND return day (Aug 13 → Aug 14 = 2 days),
    # so Total = daily_rate × days (6500 × 2 = 13000).
    daily_rate = 0
    if booking and booking.daily_rate:
        daily_rate = booking.daily_rate            # ✅ BOOKING-SPECIFIC OVERRIDE WINS (set via invoice modal)
    elif vehicle and vehicle.daily_rate:
        daily_rate = vehicle.daily_rate            # fallback: vehicle's standard rate
    elif booking and booking.total_amount and booking.start_date and booking.end_date:
        days = (booking.end_date - booking.start_date).days + 1
        daily_rate = booking.total_amount / days   # last-resort derivation (13000 / 2 = 6500)

    # 3. PREPARE CONTEXT FOR JINJA2 TEMPLATE
    context = {
        "contract": contract,
        "booking": booking,
        "client": client,
        "vehicle": vehicle,
        "tenant": tenant,
        "tenant_profile": tenant_profile,
        "signature_data_uri": signature_data_uri,
        "policies": default_policies,
        "daily_rate": daily_rate,
    }

    # 4. RENDER HTML
    template = template_env.get_template("contract_premium.html")
    html_content = template.render(**context)

    # 5. OPTIMIZED PDF GENERATION WITH BROWSER POOL
    try:
        browser = await browser_pool.get_browser()
        page = await browser.newPage()
        await page.setContent(html_content)
        await asyncio.sleep(0.3)

        pdf_bytes = await page.pdf(
            format='A4',
            printBackground=True,
            margin={
                'top': '0mm',
                'right': '0mm',
                'bottom': '0mm',
                'left': '0mm'
            }
        )

        await page.close()
        return pdf_bytes

    except Exception as e:
        print(f"❌ PUPPETEER ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise
