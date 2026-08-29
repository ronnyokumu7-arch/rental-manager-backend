import asyncio
from decimal import Decimal
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoices import Invoice
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.vehicles import Vehicle
from app.models.drivers import Driver  # ✅ MILESTONE 2
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
    driver = None  # ✅ MILESTONE 2

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

            # ✅ MILESTONE 2: Load driver if assigned
            if booking.driver_id:
                driver_stmt = select(Driver).where(Driver.id == booking.driver_id)
                driver = (await db.execute(driver_stmt)).scalars().first()

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

    # ✅ PHASE 1: Read snapshot fields directly from the booking (source of truth).
    # No re-pricing, no config table lookup, no day-math duplication.
    rental_days = 1
    daily_rate = 0.0
    driver_total = Decimal("0.00")

    if booking:
        # Locked day count (Phase 1 bookings) or legacy fallback
        rental_days = (
            booking.billable_days
            if booking.billable_days is not None
            else (booking.end_date - booking.start_date).days + 1
        )
        rental_days = max(1, rental_days)

        # Effective rate (booking snapshot → vehicle fallback)
        if booking.daily_rate:
            daily_rate = float(booking.daily_rate)
        elif vehicle and vehicle.daily_rate:
            daily_rate = float(vehicle.daily_rate)

        # ✅ Driver portion = total - vehicle_subtotal (whatever the booking paid the driver,
        # whether engine-computed or manually adjusted). Phase 1: no overtime/accommodation.
        if booking.total_amount and booking.daily_rate:
            vehicle_subtotal = Decimal(str(booking.daily_rate)) * rental_days
            driver_total = max(
                Decimal("0.00"),
                Decimal(str(booking.total_amount)) - vehicle_subtotal,
            )

    # ✅ PHASE 1 driver fee breakdown — self-drive has no overtime/accommodation
    driver_fees_breakdown = {
        "driver_daily": driver_total,       # self-drive: all driver fees roll into daily
        "driver_overtime": Decimal("0.00"),
        "driver_accommodation": Decimal("0.00"),
        "driver_total": driver_total,
    }

    # 3. PREPARE CONTEXT
    context = {
        "invoice": invoice,
        "booking": booking,
        "client": client,
        "vehicle": vehicle,
        "driver": driver,  # ✅ MILESTONE 2
        "tenant": tenant,
        "tenant_profile": profile,
        "amount_due": amount_due,
        "amount_paid": amount_paid,
        "balance": balance,
        "rental_days": rental_days,
        "daily_rate": daily_rate,
        "driver_fees": driver_fees_breakdown,  # ✅ MILESTONE 2
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
