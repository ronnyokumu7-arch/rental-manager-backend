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
from app.services.pricing import get_pricing_config, resolve_driver_fees  # ✅ MILESTONE 2

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
    
    # Determine rental days and daily rate for itemization
    rental_days = 1
    daily_rate = 0.0
    if booking:
        rental_days = (booking.end_date - booking.start_date).days + 1
        if booking.daily_rate:
            daily_rate = float(booking.daily_rate)
        elif vehicle and vehicle.daily_rate:
            daily_rate = float(vehicle.daily_rate)

    # ✅ MILESTONE 2: Calculate driver fee breakdown for invoice line items
    driver_fees_breakdown = {
        "driver_daily": Decimal("0.00"),
        "driver_overtime": Decimal("0.00"),
        "driver_accommodation": Decimal("0.00"),
        "driver_total": Decimal("0.00"),
    }
    
    if booking and driver and booking.service_type != "selfdrive":
        try:
            config = await get_pricing_config(db, booking.tenant_id, booking.service_type)
            fees = resolve_driver_fees(driver, config)
            
            # Calculate days (same logic as pricing engine)
            pickup = booking.pickup_at or booking.start_date
            return_at = booking.scheduled_return_at or booking.end_date
            if pickup and return_at:
                elapsed_seconds = (return_at - pickup).total_seconds()
                day_hours = booking.pricing_day_hours or (config.day_hours if config else 24)
                day_seconds = day_hours * 3600
                full_days = int(elapsed_seconds // day_seconds)
                included_days = max(1, full_days)
                
                # Driver daily fee
                if fees["driver_daily_fee"]:
                    driver_fees_breakdown["driver_daily"] = Decimal(str(fees["driver_daily_fee"])) * included_days
                
                # Driver overtime (only if extra_hours > 0, which we don't track on booking)
                # Skip for now — would require re-running full pricing calculation
                
                # Driver accommodation (nights = included_days - 1)
                nights = max(0, included_days - 1)
                if fees["driver_night_accommodation_fee"] and nights:
                    driver_fees_breakdown["driver_accommodation"] = Decimal(str(fees["driver_night_accommodation_fee"])) * nights
                
                driver_fees_breakdown["driver_total"] = (
                    driver_fees_breakdown["driver_daily"] +
                    driver_fees_breakdown["driver_overtime"] +
                    driver_fees_breakdown["driver_accommodation"]
                )
        except Exception as e:
            print(f"⚠️ Failed to calculate driver fees for invoice: {e}")

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
