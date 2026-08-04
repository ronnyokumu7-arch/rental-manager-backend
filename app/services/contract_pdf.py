# app/services/contract_pdf.py

import os
import base64
import asyncio
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contracts import Contract
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.vehicles import Vehicle
from app.models.tenants import Tenant
from app.models.tenant_profile import TenantProfile
from app.services.browser_pool import browser_pool

BASE_DIR = Path(__file__).resolve().parent.parent
template_env = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(['html', 'xml'])
)

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

    # 2. BULLETPROOF SIGNATURE HANDLING (Base64 Encoding)
    signature_data_uri = None
    if contract.signed_by_client and contract.signature_image_path:
        try:
            if os.path.exists(contract.signature_image_path):
                with open(contract.signature_image_path, "rb") as img_file:
                    img_data = base64.b64encode(img_file.read()).decode('utf-8')
                    signature_data_uri = f"data:image/png;base64,{img_data}"
            else:
                print(f"⚠️ Signature file not found: {contract.signature_image_path}")
        except Exception as e:
            print(f"❌ Error encoding signature: {e}")

    default_policies = [
        "FUEL POLICY: Vehicle must be returned with the same fuel level as at pickup. Standard refueling fee applies if returned below level.",
        "MILEAGE LIMITS: Daily cap is 550 KM. Excess mileage is billed at KES 50/KM.",
        "LATE RETURNS: Returns over 2 hours late are treated as a new rental day (daily rates apply)."
    ]

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
    }

    # 4. RENDER HTML
    template = template_env.get_template("contract_premium.html")
    html_content = template.render(**context)

    # 5. OPTIMIZED PDF GENERATION WITH BROWSER POOL
    try:
        # This will now automatically restart Chrome if the previous one died
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
