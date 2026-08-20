import asyncio
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoices import Invoice
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

async def generate_invoice_pdf(invoice: Invoice, db: AsyncSession) -> bytes:
    # 1. ASYNC DATA FETCHING
    booking = None
    client = None
    vehicle = None
    
    if invoice.booking_id:
        booking_stmt = select(Booking).where(Booking.id == invoice.booking_id)
        booking = (await db.execute(booking_stmt)).scalars().first()
        
        if booking:
            if booking.client_id:
                client_stmt = select(Client).where(Client.id == booking.client_id)
                client = (await db.execute(client_stmt)).scalars().first()
            if booking.vehicle_id:
                vehicle_stmt = select(Vehicle).where(Vehicle.id == booking.vehicle_id)
                vehicle = (await db.execute(vehicle_stmt)).scalars().first()

    tenant_stmt = select(Tenant).where(Tenant.id == invoice.tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    
    profile = None
    if tenant:
        profile_stmt = select(TenantProfile).where(TenantProfile.tenant_id == invoice.tenant_id)
        profile = (await db.execute(profile_stmt)).scalars().first()

    # 2. CALCULATE FINANCIALS
    amount_due = float(invoice.amount_due) if invoice.amount_due else 0.0
    amount_paid = float(invoice.amount_paid) if invoice.amount_paid else 0.0
    balance = amount_due - amount_paid
    
    # Determine rental days and daily rate for itemization
    rental_days = 1
    daily_rate = 0.0
    if booking:
        rental_days = (booking.end_date - booking.start_date).days + 1
        if booking.daily_rate:
            daily_rate = float(booking.daily_rate)
        elif vehicle and vehicle.daily_rate:
            daily_rate = float(vehicle.daily_rate)

    # 3. PREPARE CONTEXT
    context = {
        "invoice": invoice,
        "booking": booking,
        "client": client,
        "vehicle": vehicle,
        "tenant": tenant,
        "tenant_profile": profile,
        "amount_due": amount_due,
        "amount_paid": amount_paid,
        "balance": balance,
        "rental_days": rental_days,
        "daily_rate": daily_rate,
    }

    # 4. RENDER HTML
    template = template_env.get_template("invoice_premium.html")
    html_content = template.render(**context)

    # 5. GENERATE PDF WITH BROWSER POOL (Puppeteer)
    try:
        browser = await browser_pool.get_browser()
        page = await browser.newPage()
        await page.setContent(html_content)
        await asyncio.sleep(0.3)
        
        pdf_bytes = await page.pdf(
            format='A4',
            printBackground=True,
            margin={'top': '0mm', 'right': '0mm', 'bottom': '0mm', 'left': '0mm'}
        )
        
        await page.close()
        return pdf_bytes
        
    except Exception as e:
        print(f"❌ INVOICE PDF ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise
