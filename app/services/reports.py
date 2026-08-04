# app/services/reports.py

from io import BytesIO
from datetime import datetime, timezone
from calendar import monthrange
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoices import Invoice, InvoiceStatus
from app.models.tenants import Tenant


# =====================================================================
# COMPREHENSIVE STUBS (Satisfies ALL router imports to prevent crashes)
# These are synchronous to match the router's current unawaited calls.
# =====================================================================

def build_excel_report(report_type: str, data: dict, tenant_name: str) -> bytes:
    raise NotImplementedError(f"Excel report '{report_type}' is not yet implemented.")

def build_overdue_pdf(data: dict, tenant_name: str) -> bytes:
    raise NotImplementedError("Overdue PDF report generation is not yet implemented.")

def build_revenue_pdf(data: dict, tenant_name: str) -> bytes:
    raise NotImplementedError("Revenue PDF report generation is not yet implemented.")

def build_vehicle_utilisation_pdf(data: dict, tenant_name: str) -> bytes:
    raise NotImplementedError("Vehicle utilisation PDF report generation is not yet implemented.")

def get_booking_summary(db, tenant_id, start_date, end_date):
    raise NotImplementedError("Booking summary report generation is not yet implemented.")

def get_client_activity(db, tenant_id, start_date, end_date):
    raise NotImplementedError("Client activity report generation is not yet implemented.")

def get_overdue_bookings(db, tenant_id):
    raise NotImplementedError("Overdue bookings report generation is not yet implemented.")

def get_platform_revenue(db):
    raise NotImplementedError("Platform revenue report generation is not yet implemented.")

def get_revenue_summary(db, tenant_id, start_date, end_date):
    raise NotImplementedError("Revenue summary report generation is not yet implemented.")

def get_subscription_health(db):
    raise NotImplementedError("Subscription health report generation is not yet implemented.")

def get_vehicle_utilisation(db, tenant_id, start_date, end_date):
    raise NotImplementedError("Vehicle utilisation report generation is not yet implemented.")


# =====================================================================
# REAL IMPLEMENTATION: Monthly Revenue Report (Async)
# =====================================================================

async def generate_monthly_revenue_report(
    tenant_id: int, month: int, year: int, db: AsyncSession
) -> bytes:
    """Generates a Monthly Revenue Summary PDF for a specific tenant."""
    start_date = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_day = monthrange(year, month)[1]
    end_date = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    month_name = start_date.strftime("%B %Y")
    
    tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    
    stats_stmt = select(
        func.count(Invoice.id).label("count"),
        func.coalesce(func.sum(Invoice.amount_paid), 0).label("total"),
    ).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status == InvoiceStatus.paid,
        Invoice.paid_at >= start_date,
        Invoice.paid_at <= end_date,
    )
    stats = (await db.execute(stats_stmt)).first()
    invoice_count = stats.count or 0
    total_revenue = Decimal(str(stats.total or 0))
    avg_invoice = total_revenue / invoice_count if invoice_count > 0 else Decimal("0")
    
    invoices_stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == InvoiceStatus.paid,
            Invoice.paid_at >= start_date,
            Invoice.paid_at <= end_date,
        )
        .order_by(Invoice.paid_at.asc())
    )
    invoices = (await db.execute(invoices_stmt)).scalars().all()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    brand_color = colors.HexColor("#1a1a2e")
    
    elements = []
    company_name = tenant.name if tenant else "Rental Agency"
    elements.append(Paragraph(company_name, ParagraphStyle("CompanyName", fontSize=14, textColor=colors.HexColor("#888888"), spaceAfter=4)))
    elements.append(Paragraph("Monthly Revenue Report", ParagraphStyle("ReportTitle", parent=styles["Heading1"], fontSize=22, textColor=brand_color, spaceAfter=4)))
    elements.append(Paragraph(month_name, ParagraphStyle("ReportSubtitle", parent=styles["Normal"], fontSize=12, textColor=colors.HexColor("#666666"), spaceAfter=16)))
    elements.append(Spacer(1, 5 * mm))
    
    summary_data = [
        ["Total Revenue", "Invoice Count", "Average Invoice"],
        [f"KES {total_revenue:,.2f}", str(invoice_count), f"KES {avg_invoice:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[60*mm, 40*mm, 60*mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand_color), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, 1), 14), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (-1, 1), brand_color), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 10 * mm))
    
    elements.append(Paragraph("Paid Invoices", ParagraphStyle("SectionHeader", fontSize=14, textColor=brand_color, spaceAfter=8)))
    
    if invoice_count == 0:
        elements.append(Paragraph("<i>No paid invoices found for this period.</i>", styles["Normal"]))
    else:
        invoice_rows = [["Date", "Invoice #", "Amount", "Currency"]]
        for inv in invoices:
            paid_date = inv.paid_at.strftime("%d %b %Y") if inv.paid_at else "—"
            invoice_rows.append([paid_date, inv.invoice_number, f"{float(inv.amount_paid):,.2f}", inv.currency_code])
        
        invoice_table = Table(invoice_rows, colWidths=[35*mm, 40*mm, 45*mm, 30*mm])
        invoice_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), brand_color), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey), ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("ALIGN", (2, 1), (2, -1), "RIGHT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
        ]))
        elements.append(invoice_table)
    
    elements.append(Spacer(1, 15 * mm))
    elements.append(Paragraph(f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M')} UTC", ParagraphStyle("Footer", fontSize=9, textColor=colors.HexColor("#888888"))))
    
    doc.build(elements)
    return buffer.getvalue()
