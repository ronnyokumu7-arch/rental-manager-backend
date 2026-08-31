from app.core.config import get_settings
from app.services.email.client import _send
from app.services.email.templates import _premium_template, _format_currency

settings = get_settings()


async def send_contract_to_client(
    to: str, client_name: str, contract_number: str, vehicle: str,
    start_date: str, end_date: str, total_amount: str, currency: str, contract_url: str,
) -> bool:
    body = f"""
    <p>Dear {client_name},</p>
    <p>Your rental contract is ready for review and signature.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Contract Number</td><td>{contract_number}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
        <tr><td>Rental Period</td><td>{start_date} — {end_date}</td></tr>
        <tr><td>Total Amount</td><td>{_format_currency(total_amount, currency)}</td></tr>
    </table>
    
    <p>Please review the contract carefully and sign it electronically.</p>
    <p style="font-size: 13px; color: #78716C;">This link will expire in 30 days.</p>
    """
    return await _send(
        to,
        f"Your Rental Contract — {contract_number}",
        _premium_template(
            title="Contract Ready for Signature",
            body=body,
            cta_text="Review & Sign Contract",
            cta_url=contract_url,
            preview_text=f"Contract {contract_number} is ready for your signature.",
        )
    )


async def send_invoice_to_client(
    to: str, client_name: str, invoice_number: str, amount_due: str,
    currency: str, due_date: str, invoice_url: str = "",
) -> bool:
    body = f"""
    <p>Dear {client_name},</p>
    <p>An invoice has been issued for your recent rental.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Invoice Number</td><td>{invoice_number}</td></tr>
        <tr><td>Amount Due</td><td>{_format_currency(amount_due, currency)}</td></tr>
        <tr><td>Due Date</td><td>{due_date}</td></tr>
    </table>
    
    <p>Please review the details and arrange payment at your earliest convenience.</p>
    """
    return await _send(
        to,
        f"Invoice {invoice_number} — Payment Due",
        _premium_template(
            title="Invoice Issued",
            body=body,
            cta_text="View Invoice",
            cta_url=invoice_url or f"{settings.frontend_url}/invoices",
            preview_text=f"Invoice {invoice_number} is now available.",
        )
    )


async def send_quotation_to_client(
    to: str, client_name: str, quotation_id: int, quotation_url: str,
    total_amount: str, currency: str, expires_at: str,
) -> bool:
    body = f"""
    <p>Dear {client_name},</p>
    <p>We have prepared a rental quotation for your review.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Quotation ID</td><td>#{quotation_id}</td></tr>
        <tr><td>Total Amount</td><td>{_format_currency(total_amount, currency)}</td></tr>
        <tr><td>Valid Until</td><td>{expires_at}</td></tr>
    </table>
    
    <p>Please review the details and accept the quotation at your earliest convenience.</p>
    <p style="font-size: 13px; color: #78716C;">This quotation expires on the date specified above.</p>
    """
    return await _send(
        to,
        f"Your Rental Quotation #{quotation_id}",
        _premium_template(
            title="Quotation Ready for Review",
            body=body,
            cta_text="Review Quotation",
            cta_url=quotation_url,
            preview_text=f"Quotation #{quotation_id} is ready for your review.",
        )
    )
