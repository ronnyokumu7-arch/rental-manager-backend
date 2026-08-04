"""
Sequential number generator for tenant-scoped, monthly-resetting document numbers.

Format: {PREFIX}{YYYY}{MM}{###}
- PREFIX: 'C' for contracts, 'B' for bookings, 'I' for invoices
- YYYY: 4-digit year
- MM: 2-digit month (01-12)
- ###: 3-digit counter (001-999) that resets to 001 on the 1st of each month

Examples:
- C202607001 = Contract #1 in July 2026
- B202607042 = Booking #42 in July 2026
- I202608003 = Invoice #3 in August 2026
"""
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def generate_document_number(
    db: AsyncSession,
    model_class,
    tenant_id: int,
    prefix: str,
    number_column_name: str = "contract_number",
) -> str:
    """
    Generate a tenant-scoped, monthly-resetting document number.
    
    Args:
        db: Async database session
        model_class: The SQLAlchemy model (Contract, Booking, or Invoice)
        tenant_id: The tenant ID for scoping
        prefix: Single character prefix ('C', 'B', or 'I')
        number_column_name: Name of the column storing the number
    
    Returns:
        Formatted document number (e.g., "C202607001")
    
    Raises:
        ValueError: If prefix is invalid or counter exceeds 999
    """
    if len(prefix) != 1 or not prefix.isalpha():
        raise ValueError(f"Prefix must be a single letter, got: {prefix}")
    
    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month
    month_prefix = f"{prefix}{year}{month:02d}"  # e.g., "C202607"
    
    # Get the column object dynamically
    number_column = getattr(model_class, number_column_name)
    
    # Find the highest number for this tenant in the current month
    stmt = (
        select(number_column)
        .where(
            model_class.tenant_id == tenant_id,
            number_column.like(f"{month_prefix}%")
        )
        .order_by(number_column.desc())
        .limit(1)
    )
    
    result = await db.execute(stmt)
    last_number = result.scalar_one_or_none()
    
    if last_number:
        # Extract the 3-digit counter from the end (e.g., "C202607042" -> 42)
        try:
            last_counter = int(last_number[-3:])
            new_counter = last_counter + 1
        except (ValueError, IndexError):
            new_counter = 1
    else:
        new_counter = 1
    
    # Safety check: prevent overflow beyond 999
    if new_counter > 999:
        raise ValueError(
            f"Monthly capacity exceeded for {prefix} documents in tenant {tenant_id}. "
            f"Counter reached {new_counter}, max is 999."
        )
    
    return f"{month_prefix}{new_counter:03d}"


# Convenience wrappers for each document type
async def generate_contract_number(db: AsyncSession, tenant_id: int) -> str:
    from app.models.contracts import Contract
    return await generate_document_number(db, Contract, tenant_id, "C", "contract_number")


async def generate_booking_number(db: AsyncSession, tenant_id: int) -> str:
    from app.models.bookings import Booking
    return await generate_document_number(db, Booking, tenant_id, "B", "booking_number")


async def generate_invoice_number(db: AsyncSession, tenant_id: int) -> str:
    from app.models.invoices import Invoice
    return await generate_document_number(db, Invoice, tenant_id, "I", "invoice_number")
