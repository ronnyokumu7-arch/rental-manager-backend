from typing import List
from app.services.email.client import _send
from app.services.email.templates import _premium_template, _format_currency


async def send_booking_confirmation(
    to: str, client_name: str, booking_id: int, vehicle: str,
    start_date: str, end_date: str, total_amount: str, currency: str, contract_number: str,
) -> bool:
    body = f"""
    <p>Dear {client_name},</p>
    <p>Thank you for choosing <strong>Rental Garage</strong>. Your booking has been received and is currently being processed.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Booking Reference</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
        <tr><td>Pick-up Date</td><td>{start_date}</td></tr>
        <tr><td>Return Date</td><td>{end_date}</td></tr>
        <tr><td>Total Amount</td><td>{_format_currency(total_amount, currency)}</td></tr>
        <tr><td>Contract</td><td>{contract_number}</td></tr>
    </table>
    
    <p style="margin-top: 8px;">Status: <span class="badge badge-pending">Pending Confirmation</span></p>
    
    <p>You will receive a confirmation email once your booking is approved. Please review your rental agreement carefully.</p>
    """
    return await _send(
        to,
        f"Booking Received — #{booking_id}",
        _premium_template(
            title="Booking Received",
            body=body,
            preview_text=f"Your rental request for {vehicle} is being processed.",
        )
    )


async def send_booking_confirmed(
    to: str, client_name: str, booking_id: int, vehicle: str, start_date: str,
) -> bool:
    body = f"""
    <p>Dear {client_name},</p>
    <p><strong>Great news!</strong> Your booking has been confirmed.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Booking Reference</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
        <tr><td>Pick-up Date</td><td>{start_date}</td></tr>
    </table>
    
    <p style="margin-top: 8px;">Status: <span class="badge badge-confirmed">Confirmed</span></p>
    
    <p>Please ensure you bring your valid driver's license and identification on the pick-up day.</p>
    """
    return await _send(
        to,
        f"Booking Confirmed — #{booking_id}",
        _premium_template(
            title="Booking Confirmed",
            body=body,
            preview_text=f"Your booking for {vehicle} has been confirmed.",
        )
    )


async def send_booking_activated(
    to: str, client_name: str, booking_id: int, vehicle: str, end_date: str,
) -> bool:
    body = f"""
    <p>Dear {client_name},</p>
    <p>Your rental has started! Enjoy your journey with <strong>{vehicle}</strong>.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Booking Reference</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
        <tr><td>Return By</td><td>{end_date}</td></tr>
    </table>
    
    <p style="margin-top: 8px;">Status: <span class="badge badge-active">Active</span></p>
    
    <p>Please return the vehicle by the date above. Late returns will incur additional charges.</p>
    """
    return await _send(
        to,
        f"Your Rental Has Started — #{booking_id}",
        _premium_template(
            title="Rental Started",
            body=body,
            preview_text=f"Your rental for {vehicle} is now active.",
        )
    )


async def send_booking_completed(
    to: str, client_name: str, booking_id: int, vehicle: str,
) -> bool:
    body = f"""
    <p>Dear {client_name},</p>
    <p>Your rental has been successfully completed. <strong>Thank you for choosing Rental Garage!</strong></p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Booking Reference</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
    </table>
    
    <p style="margin-top: 8px;">Status: <span class="badge badge-completed">Completed</span></p>
    
    <p>We hope you had a great experience. We look forward to serving you again.</p>
    """
    return await _send(
        to,
        f"Rental Complete — #{booking_id}",
        _premium_template(
            title="Rental Completed",
            body=body,
            preview_text="Thank you for choosing Rental Garage.",
        )
    )


async def send_booking_cancelled(
    to: str | List[str], client_name: str, booking_id: int, vehicle: str,
) -> bool:
    body = f"""
    <p>Dear {client_name},</p>
    <p>Booking <strong>#{booking_id}</strong> has been cancelled.</p>
    
    <div class="divider"></div>
    
    <table class="detail-table">
        <tr><td>Booking Reference</td><td>#{booking_id}</td></tr>
        <tr><td>Vehicle</td><td>{vehicle}</td></tr>
    </table>
    
    <p style="margin-top: 8px;">Status: <span class="badge badge-cancelled">Cancelled</span></p>
    
    <p>If you have any questions, please contact your rental company directly.</p>
    """
    return await _send(
        to,
        f"Booking Cancelled — #{booking_id}",
        _premium_template(
            title="Booking Cancelled",
            body=body,
            preview_text=f"Booking #{booking_id} has been cancelled.",
        )
    )
