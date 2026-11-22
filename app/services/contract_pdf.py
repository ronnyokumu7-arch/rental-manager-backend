import os
import base64
import asyncio
import urllib.request
from decimal import Decimal
from typing import Optional, Any
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.contracts import Contract
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.vehicles import Vehicle
from app.models.drivers import Driver
from app.models.tenants import Tenant
from app.models.tenant_profile import TenantProfile
from app.services.browser_pool import browser_pool
from app.services.storage import get_backend
from app.services.business_policy import get_effective_policy_document
from app.services.markdown_lite import markdown_to_html

BASE_DIR = Path(__file__).resolve().parent.parent
template_env = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(['html', 'xml'])
)

template_env.filters['markdown_to_html'] = markdown_to_html


async def resolve_signature_data_uri(obj: Any, attr_name: str = "signature_image_path") -> Optional[str]:
    """
    ✅ OPTIMIZED SIGNATURE RESOLVER
    Reduced timeout from 15s to 3s to prevent hanging on slow storage responses.
    """
    ref = getattr(obj, attr_name, None) if not isinstance(obj, str) else obj
    if not ref:
        return None

    loop = asyncio.get_running_loop()

    def _fetch(url: str) -> Optional[bytes]:
        try:
            # ✅ OPTIMIZATION: 3-second timeout prevents event loop blocking
            with urllib.request.urlopen(url, timeout=3) as resp:
                return resp.read()
        except Exception as e:
            print(f"❌ Failed to fetch signature bytes ({attr_name}): {e}")
            return None

    def _to_data_uri(data: bytes) -> str:
        return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")

    api_base = get_settings().public_url_base.rstrip("/")
    files_prefix = f"{api_base}/api/v1/files/"
    
    if ref.startswith(files_prefix):
        relative_path = ref[len(files_prefix):].lstrip("/")
        backend = get_backend()
        signed = backend.signed_url(relative_path, ttl_seconds=300)
        if signed:
            data = await loop.run_in_executor(None, _fetch, signed)
            if data:
                return _to_data_uri(data)

        upload_dir = Path(get_settings().uploads_dir).resolve()
        local_path = (upload_dir / relative_path).resolve()
        try:
            local_path.relative_to(upload_dir)
            if local_path.exists() and local_path.is_file():
                with open(local_path, "rb") as f:
                    return _to_data_uri(f.read())
        except ValueError:
            pass
        return None

    if ref.startswith("http://") or ref.startswith("https://"):
        data = await loop.run_in_executor(None, _fetch, ref)
        if data:
            return _to_data_uri(data)
        return None

    if ref.startswith("data:"):
        return ref

    if os.path.exists(ref):
        try:
            with open(ref, "rb") as img_file:
                return _to_data_uri(img_file.read())
        except Exception:
            return None

    return None


async def generate_contract_pdf(contract: Contract, db: AsyncSession) -> bytes:
    # 1. ✅ OPTIMIZED SINGLE QUERY with eager loading (Replaces 6 separate queries)
    stmt = (
        select(Contract)
        .options(
            selectinload(Contract.booking).selectinload(Booking.client),
            selectinload(Contract.booking).selectinload(Booking.vehicle),
            selectinload(Contract.booking).selectinload(Booking.driver),
            selectinload(Contract.booking).selectinload(Booking.tenant).selectinload(Tenant.profile),
        )
        .where(Contract.id == contract.id)
    )
    result = await db.execute(stmt)
    loaded_contract = result.scalars().unique().first()
    
    if not loaded_contract or not loaded_contract.booking:
        raise ValueError("Contract or associated booking not found")
        
    booking = loaded_contract.booking
    client = booking.client
    vehicle = booking.vehicle
    driver = booking.driver
    tenant = booking.tenant
    tenant_profile = tenant.profile if tenant else None

    # 2. ✅ SIGNATURES: resolve via storage service
    signature_data_uri = None
    if loaded_contract.signed_by_client:
        signature_data_uri = await resolve_signature_data_uri(loaded_contract, "signature_image_path")

    handover_signature_data_uri = None
    if loaded_contract.handover_signed_at:
        handover_signature_data_uri = await resolve_signature_data_uri(loaded_contract, "handover_signature_image_path")

    company_signature_data_uri = None
    if tenant_profile and getattr(tenant_profile, "company_signature_path", None):
        company_signature_data_uri = await resolve_signature_data_uri(tenant_profile, "company_signature_path")

    policy_doc = await get_effective_policy_document(db, loaded_contract.tenant_id)

    # 3. PREPARE CONTEXT FOR JINJA2 TEMPLATE
    daily_rate = Decimal("0.00")
    rental_days = 1

    if booking:
        rental_days = (
            booking.billable_days
            if booking.billable_days is not None
            else (booking.end_date - booking.start_date).days + 1
        )
        rental_days = max(1, rental_days)

        if booking.daily_rate:
            daily_rate = Decimal(str(booking.daily_rate))
        elif vehicle and vehicle.daily_rate:
            daily_rate = Decimal(str(vehicle.daily_rate))
        elif booking.total_amount:
            daily_rate = Decimal(str(booking.total_amount)) / Decimal(rental_days)

    driver_total = Decimal("0.00")
    if booking and booking.total_amount and daily_rate:
        vehicle_subtotal = daily_rate * Decimal(rental_days)
        driver_total = max(Decimal("0.00"), Decimal(str(booking.total_amount)) - vehicle_subtotal)

    driver_fees_breakdown = {
        "driver_daily": driver_total,
        "driver_overtime": Decimal("0.00"),
        "driver_accommodation": Decimal("0.00"),
        "driver_total": driver_total,
    }

    context = {
        "contract": loaded_contract,
        "booking": booking,
        "client": client,
        "vehicle": vehicle,
        "driver": driver,
        "tenant": tenant,
        "tenant_profile": tenant_profile,
        "signature_data_uri": signature_data_uri,
        "handover_signature_data_uri": handover_signature_data_uri,
        "company_signature_data_uri": company_signature_data_uri,
        "policy_doc": policy_doc,
        "daily_rate": daily_rate,
        "driver_fees": driver_fees_breakdown,
    }

    # 4. RENDER HTML
    template = template_env.get_template("contract_premium.html")
    html_content = template.render(**context)

    # 5. ✅ OPTIMIZED PDF GENERATION (No unnecessary sleep, preferCSSPageSize)
    try:
        browser = await browser_pool.get_browser()
        page = await browser.newPage()
        
        # ✅ OPTIMIZATION: preferCSSPageSize lets the @page rule handle sizing instantly
        await page.setContent(html_content, {"waitUntil": "networkidle0", "timeout": 5000})

        pdf_bytes = await page.pdf(
            format='A4',
            printBackground=True,
            preferCSSPageSize=True, # ✅ Faster rendering
            margin={'top': '0mm', 'right': '0mm', 'bottom': '0mm', 'left': '0mm'}
        )

        await page.close()
        return pdf_bytes

    except Exception as e:
        error_msg = str(e)
        if "Connection is closed" in error_msg or "Connection closed" in error_msg:
            print("⚠️ Browser died mid-render. Forcing restart and retrying...")
            try:
                browser = await browser_pool.get_browser(force_restart=True)
                page = await browser.newPage()
                await page.setContent(html_content, {"waitUntil": "networkidle0", "timeout": 5000})

                pdf_bytes = await page.pdf(
                    format='A4',
                    printBackground=True,
                    preferCSSPageSize=True,
                    margin={'top': '0mm', 'right': '0mm', 'bottom': '0mm', 'left': '0mm'}
                )
                await page.close()
                return pdf_bytes
            except Exception as retry_err:
                print(f"❌ PDF retry failed: {retry_err}")
                import traceback
                traceback.print_exc()
                raise retry_err
        
        print(f"❌ PUPPETEER ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise
