# app/services/pdf.py
from io import BytesIO
from datetime import datetime, timezone
from decimal import Decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from sqlalchemy.orm import Session

from app.models.invoices import Invoice
from app.models.contracts import Contract
from app.models.tenants import Tenant
from app.models.tenant_profile import TenantProfile
from app.models.tenant_policies import TenantPolicy
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.vehicles import Vehicle

def generate_invoice_pdf(invoice: Invoice, db: Session) -> bytes:
    tenant = db.query(Tenant).filter(Tenant.id == invoice.tenant_id).first()
    profile = db.query(TenantProfile).filter(TenantProfile.tenant_id == invoice.tenant_id).first()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    brand_color = colors.HexColor("#1a1a2e")
    accent_color = colors.HexColor("#4f8cff")

    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=24, textColor=brand_color, spaceAfter=4)
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#555555"))

    elements = []
    elements.append(Paragraph("INVOICE", title_style))
    elements.append(Paragraph(f"#{invoice.invoice_number}", ParagraphStyle("InvNum", parent=styles["Normal"], fontSize=13, textColor=accent_color, spaceAfter=16)))

    # --- META DATA TABLE ---
    meta = [
        ["Billed To", "Invoice Date", "Due Date", "Status"],
        [
            tenant.name if tenant else "—",
            invoice.created_at.strftime("%d %b %Y") if invoice.created_at else "—",
            invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "—",
            invoice.status.value.upper(),
        ],
    ]
    meta_table = Table(meta, colWidths=[50 * mm, 40 * mm, 40 * mm, 40 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica"), ("FONTSIZE", (0, 0), (-1, 0), 8), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#888888")),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"), ("FONTSIZE", (0, 1), (-1, 1), 11), ("TEXTCOLOR", (0, 1), (-1, 1), brand_color),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#dddddd")),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 10 * mm))

    # --- DYNAMIC LINE ITEMS ---
    line_items = [["Description", "Amount"]]
    
    if invoice.booking_id:
        # It's a Rental Invoice
        booking = db.query(Booking).filter(Booking.id == invoice.booking_id).first()
        vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first() if booking else None
        client = db.query(Client).filter(Client.id == booking.client_id).first() if booking else None
        
        desc = f"<b>Vehicle Rental</b><br/>{vehicle.make} {vehicle.model} ({vehicle.plate_number})<br/>" if vehicle else "Vehicle Rental<br/>"
        if booking:
            desc += f"Period: {booking.start_date.strftime('%d %b %Y')} - {booking.end_date.strftime('%d %b %Y')}<br/>"
            desc += f"Client: {client.full_name if client else 'N/A'}"
        
        line_items.append([desc, f"{invoice.currency_code} {invoice.amount_due:,.2f}"])
    else:
        # It's a Subscription/System Invoice
        line_items.append([f"Subscription Service — {invoice.subscription_id or 'Manual'}", f"{invoice.currency_code} {invoice.amount_due:,.2f}"])

    if invoice.notes:
        line_items.append([f"<i>{invoice.notes}</i>", ""])

    items_table = Table(line_items, colWidths=[130 * mm, 40 * mm])
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand_color), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 6 * mm))

    # --- TOTALS ---
    totals = [
        ["Amount Due", f"{invoice.currency_code} {invoice.amount_due:,.2f}"],
        ["Amount Paid", f"{invoice.currency_code} {invoice.amount_paid:,.2f}"],
        ["Balance", f"{invoice.currency_code} {max(invoice.amount_due - invoice.amount_paid, Decimal('0')):,.2f}"],
    ]
    totals_table = Table(totals, colWidths=[130 * mm, 40 * mm])
    totals_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 10), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"), ("FONTSIZE", (0, 2), (-1, 2), 12), ("TEXTCOLOR", (0, 2), (-1, 2), brand_color),
        ("LINEABOVE", (0, 2), (-1, 2), 1, brand_color), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 16 * mm))
    
    elements.append(Paragraph("Thank you for your business. Please settle any outstanding balance by the due date.", small_style))
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M')} UTC", small_style))

    doc.build(elements)
    return buffer.getvalue()

def generate_contract_pdf(contract: Contract, db: Session) -> bytes:
    # ... (Keep your existing generate_contract_pdf code exactly as it was) ...
    # I am omitting it here to save space, but DO NOT DELETE IT from your file.
    # Just replace the generate_invoice_pdf function above.
    pass 
