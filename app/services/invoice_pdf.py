# app/services/invoice_pdf.py

from io import BytesIO
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoices import Invoice
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.vehicles import Vehicle
from app.models.tenants import Tenant
from app.models.tenant_profile import TenantProfile


async def generate_invoice_pdf(invoice: Invoice, db: AsyncSession) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=20*mm, 
        leftMargin=20*mm, 
        topMargin=20*mm, 
        bottomMargin=20*mm
    )

    # ✅ ASYNC DATA FETCHING
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

    styles = getSampleStyleSheet()
    brand_color = colors.HexColor("#1a1a2e")
    accent_color = colors.HexColor("#4f8cff")
    
    # Custom Styles
    header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=10, textColor=colors.grey, spaceAfter=4)
    
    elements = []

    # --- HEADER SECTION ---
    # Left: Logo & Company Name
    left_col = []
    
    # ✅ FIX 1: Safely resolve absolute path for the logo
    if profile and profile.logo_url:
        logo_path = os.path.abspath(profile.logo_url)
        if os.path.exists(logo_path):
            left_col.append(Image(logo_path, width=40*mm, height=20*mm))
            
    left_col.append(Paragraph(
        tenant.name if tenant else "Rental Agency", 
        ParagraphStyle('CompanyName', fontSize=16, textColor=brand_color, spaceAfter=2)
    ))
    if profile:
        left_col.append(Paragraph(profile.address or "", styles['Normal']))
        left_col.append(Paragraph(f"Phone: {profile.phone or 'N/A'}", styles['Normal']))
    
    # Right: Invoice Details
    right_col = [
        Paragraph("INVOICE", ParagraphStyle('InvTitle', fontSize=20, textColor=accent_color, alignment=1)),
        Paragraph(f"<b>Invoice #:</b> {invoice.invoice_number}", styles['Normal']),
        Paragraph(f"<b>Date:</b> {invoice.created_at.strftime('%d %b %Y')}", styles['Normal']),
        Paragraph(f"<b>Due Date:</b> {invoice.due_date.strftime('%d %b %Y')}", styles['Normal']),
    ]

    # Combine into a table for layout
    header_table = Table([[left_col, right_col]], colWidths=[90*mm, 90*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LINEBELOW', (0,0), (-1,0), 1, colors.lightgrey),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('TOPPADDING', (0,0), (-1,0), 12),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 10*mm))

    # --- BILL TO SECTION ---
    elements.append(Paragraph("BILL TO", ParagraphStyle('SectionHeader', fontSize=12, textColor=brand_color, spaceAfter=4)))
    if client:
        elements.append(Paragraph(f"<b>{client.full_name}</b>", styles['Normal']))
        elements.append(Paragraph(client.phone or "", styles['Normal']))
        # ✅ FIX 2: Only append email if it exists to avoid blank lines
        if client.email:
            elements.append(Paragraph(client.email, styles['Normal']))
    elements.append(Spacer(1, 10*mm))

    # --- ITEMS TABLE ---
    items_data = [['Description', 'Amount']]
    
    desc = "Vehicle Rental"
    if vehicle and booking:
        desc = f"Rental of {vehicle.make} {vehicle.model} ({vehicle.plate_number})<br/>{booking.start_date.strftime('%d %b')} to {booking.end_date.strftime('%d %b %Y')}"
    
    # ✅ FIX 3: Cast Decimals to float for safe f-string formatting
    items_data.append([
        Paragraph(desc, styles['Normal']), 
        f"{invoice.currency_code} {float(invoice.amount_due):,.2f}"
    ])
    
    if invoice.notes:
        items_data.append([Paragraph(f"<i>Notes: {invoice.notes}</i>", styles['Normal']), ""])

    items_table = Table(items_data, colWidths=[120*mm, 60*mm])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), brand_color),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 10*mm))

    # --- TOTALS ---
    balance = float(invoice.amount_due) - float(invoice.amount_paid)
    
    totals_data = [
        ['Subtotal', f"{invoice.currency_code} {float(invoice.amount_due):,.2f}"],
        ['Amount Paid', f"{invoice.currency_code} {float(invoice.amount_paid):,.2f}"],
        ['<b>BALANCE DUE</b>', f"<b>{invoice.currency_code} {balance:,.2f}</b>"]
    ]
    totals_table = Table(totals_data, colWidths=[120*mm, 60*mm])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTNAME', (0,2), (1,2), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('LINEABOVE', (0,2), (-1,2), 1, brand_color),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(totals_table)

    doc.build(elements)
    return buffer.getvalue()
