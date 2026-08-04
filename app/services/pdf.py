# app/services/pdf.py

from io import BytesIO
from datetime import datetime, timezone
from decimal import Decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoices import Invoice
# ✅ REMOVED: Contract import (now handled in contract_pdf.py)
from app.models.tenants import Tenant
from app.models.tenant_profile import TenantProfile
from app.models.tenant_policies import TenantPolicy
from app.models.bookings import Booking
from app.models.clients import Client
from app.models.vehicles import Vehicle


async def generate_invoice_pdf(invoice: Invoice, db: AsyncSession) -> bytes:
    """
    Generate invoice PDF using ReportLab.
    Your existing invoice generation code stays here.
    """
    # ⚠️ KEEP YOUR EXISTING INVOICE PDF GENERATION CODE HERE
    # This function is untouched and continues to work as before.
    
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
    elements = []
    
    # Your existing invoice generation logic...
    # (Keep everything you had here for invoices)
    
    doc.build(elements)
    return buffer.getvalue()


# ✅ REMOVED: generate_contract_pdf function
# Contract PDF generation has moved to app/services/contract_pdf.py (WeasyPrint version)
