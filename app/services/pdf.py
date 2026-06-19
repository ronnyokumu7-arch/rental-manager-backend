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

    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"], fontSize=24,
        textColor=brand_color, spaceAfter=4,
    )
    small_style = ParagraphStyle(
        "Small", parent=styles["Normal"], fontSize=9,
        textColor=colors.HexColor("#555555"),
    )

    elements = []
    elements.append(Paragraph("INVOICE", title_style))
    elements.append(Paragraph(f"#{invoice.invoice_number}", ParagraphStyle(
        "InvNum", parent=styles["Normal"], fontSize=13,
        textColor=accent_color, spaceAfter=16,
    )))

    meta = [
        ["Billed to", "Invoice date", "Due date", "Status"],
        [
            tenant.name if tenant else "—",
            invoice.created_at.strftime("%d %b %Y") if invoice.created_at else "—",
            invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "—",
            invoice.status.value.upper(),
        ],
    ]
    meta_table = Table(meta, colWidths=[50 * mm, 40 * mm, 40 * mm, 40 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#888888")),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 11),
        ("TEXTCOLOR", (0, 1), (-1, 1), brand_color),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#dddddd")),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 10 * mm))

    line_items = [
        ["Description", "Amount"],
        [
            f"Subscription — {invoice.subscription_id or 'Manual'}",
            f"{invoice.currency_code} {invoice.amount_due:,.2f}",
        ],
    ]
    if invoice.notes:
        line_items.append([invoice.notes, ""])

    items_table = Table(line_items, colWidths=[130 * mm, 40 * mm])
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 6 * mm))

    totals = [
        ["Amount due", f"{invoice.currency_code} {invoice.amount_due:,.2f}"],
        ["Amount paid", f"{invoice.currency_code} {invoice.amount_paid:,.2f}"],
        ["Balance", f"{invoice.currency_code} {max(invoice.amount_due - invoice.amount_paid, Decimal('0')):,.2f}"],
    ]
    totals_table = Table(totals, colWidths=[130 * mm, 40 * mm])
    totals_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 2), (-1, 2), 12),
        ("TEXTCOLOR", (0, 2), (-1, 2), brand_color),
        ("LINEABOVE", (0, 2), (-1, 2), 1, brand_color),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 16 * mm))
    elements.append(Paragraph(
        "Thank you for your business. Please settle any outstanding balance by the due date.",
        small_style,
    ))
    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(
        f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M')} UTC",
        small_style,
    ))

    doc.build(elements)
    return buffer.getvalue()


def generate_contract_pdf(contract: Contract, db: Session) -> bytes:
    booking = db.query(Booking).filter(Booking.id == contract.booking_id).first()
    client = db.query(Client).filter(Client.id == booking.client_id).first()
    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    profile = db.query(TenantProfile).filter(TenantProfile.tenant_id == contract.tenant_id).first()
    policies = db.query(TenantPolicy).filter(
        TenantPolicy.tenant_id == contract.tenant_id,
        TenantPolicy.is_active == True,
    ).order_by(TenantPolicy.display_order).all()

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

    company_name = profile.company_name if profile else "Rental Company"
    contract_footer = profile.contract_footer if profile else ""

    heading_style = ParagraphStyle(
        "Heading", parent=styles["Heading1"], fontSize=20,
        textColor=brand_color, spaceAfter=2,
    )
    subheading_style = ParagraphStyle(
        "SubHeading", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#888888"), spaceAfter=12,
    )
    section_title_style = ParagraphStyle(
        "SectionTitle", parent=styles["Heading2"], fontSize=11,
        textColor=brand_color, spaceBefore=10, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=9,
        textColor=colors.HexColor("#333333"), leading=14, spaceAfter=6,
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"], fontSize=8,
        textColor=colors.HexColor("#888888"), spaceAfter=1,
    )
    value_style = ParagraphStyle(
        "Value", parent=styles["Normal"], fontSize=10,
        textColor=brand_color, spaceAfter=6,
    )
    small_style = ParagraphStyle(
        "Small", parent=styles["Normal"], fontSize=8,
        textColor=colors.HexColor("#888888"),
    )

    elements = []

    elements.append(Paragraph(company_name.upper(), heading_style))
    elements.append(Paragraph("Vehicle Rental Agreement", subheading_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=brand_color))
    elements.append(Spacer(1, 6 * mm))

    meta = [
        ["Contract No.", "Booking Date", "Status"],
        [
            contract.contract_number,
            booking.created_at.strftime("%d %b %Y") if booking.created_at else "—",
            contract.status.value.upper(),
        ],
    ]
    meta_table = Table(meta, colWidths=[60 * mm, 60 * mm, 50 * mm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#888888")),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 10),
        ("TEXTCOLOR", (0, 1), (-1, 1), brand_color),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 6 * mm))

    elements.append(Paragraph("Client Details", section_title_style))
    client_data = [
        ["Full name", client.full_name if client else "—",
         "ID number", client.id_number or "—"],
        ["Phone", client.phone if client else "—",
         "Email", client.email or "—"],
        ["Address", client.residential_address or "—", "", ""],
    ]
    client_table = Table(client_data, colWidths=[30 * mm, 60 * mm, 30 * mm, 50 * mm])
    client_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#888888")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#888888")),
        ("TEXTCOLOR", (1, 0), (1, -1), brand_color),
        ("TEXTCOLOR", (3, 0), (3, -1), brand_color),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#eeeeee")),
    ]))
    elements.append(client_table)
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph("Vehicle Details", section_title_style))
    vehicle_data = [
        ["Make & Model",
         f"{vehicle.make} {vehicle.model} ({vehicle.year})" if vehicle else "—",
         "Plate", vehicle.plate_number if vehicle else "—"],
        ["VIN", vehicle.vin or "—", "Daily rate",
         f"{booking.currency_code} {vehicle.daily_rate:,.2f}" if vehicle else "—"],
    ]
    vehicle_table = Table(vehicle_data, colWidths=[30 * mm, 60 * mm, 30 * mm, 50 * mm])
    vehicle_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#888888")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#888888")),
        ("TEXTCOLOR", (1, 0), (1, -1), brand_color),
        ("TEXTCOLOR", (3, 0), (3, -1), brand_color),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#eeeeee")),
    ]))
    elements.append(vehicle_table)
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph("Rental Period & Payment", section_title_style))
    rental_data = [
        ["Start date", booking.start_date.strftime("%d %b %Y"),
         "End date", booking.end_date.strftime("%d %b %Y")],
        ["Total amount",
         f"{booking.currency_code} {booking.total_amount:,}",
         "Duration",
         f"{(booking.end_date - booking.start_date).days} day(s)"],
    ]
    rental_table = Table(rental_data, colWidths=[30 * mm, 60 * mm, 30 * mm, 50 * mm])
    rental_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#888888")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#888888")),
        ("TEXTCOLOR", (1, 0), (1, -1), brand_color),
        ("TEXTCOLOR", (3, 0), (3, -1), brand_color),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#eeeeee")),
    ]))
    elements.append(rental_table)
    elements.append(Spacer(1, 6 * mm))

    if policies:
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")))
        elements.append(Paragraph("Terms & Conditions", section_title_style))
        for policy in policies:
            elements.append(Paragraph(policy.title, ParagraphStyle(
                "PolicyTitle", parent=styles["Normal"], fontSize=9,
                textColor=brand_color, fontName="Helvetica-Bold", spaceAfter=2,
            )))
            elements.append(Paragraph(policy.content, body_style))

    elements.append(Spacer(1, 8 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")))
    elements.append(Spacer(1, 6 * mm))

    sig_data = [
        ["Renter signature", "", "Company representative", ""],
        ["", "", "", ""],
        ["________________________", "", "________________________", ""],
        [client.full_name if client else "Renter", "",
         company_name, ""],
        [f"Date: ___________________", "",
         f"Date: ___________________", ""],
    ]
    sig_table = Table(sig_data, colWidths=[80 * mm, 10 * mm, 80 * mm, 0 * mm])
    sig_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#888888")),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(sig_table)

    if contract_footer:
        elements.append(Spacer(1, 8 * mm))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")))
        elements.append(Spacer(1, 3 * mm))
        elements.append(Paragraph(contract_footer, small_style))

    elements.append(Spacer(1, 4 * mm))
    elements.append(Paragraph(
        f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M')} UTC  |  {contract.contract_number}",
        small_style,
    ))

    doc.build(elements)
    return buffer.getvalue()