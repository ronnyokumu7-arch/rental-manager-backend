"""
Investor contract creation and management.

✅ LIFECYCLE:
  - generate_investor_contract → creates contract for monthly or daily leases
  - render_and_store_investor_contract_pdf → background PDF renderer
"""
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.investor_contracts import InvestorContract, InvestorContractStatus
from app.models.vehicles import Vehicle
from app.models.users import User

CONTRACTS_DIR = "storage/contracts/investor"


def _ensure_dir():
    os.makedirs(CONTRACTS_DIR, exist_ok=True)


async def get_investor_contract_by_token(db: AsyncSession, token: str) -> Optional[InvestorContract]:
    """Fetch contract by share token."""
    stmt = select(InvestorContract).where(
        InvestorContract.share_token == token
    )
    return (await db.execute(stmt)).scalars().first()


async def get_investor_contract(db: AsyncSession, contract_id: int, tenant_id: int) -> Optional[InvestorContract]:
    """Fetch contract by ID scoped to tenant."""
    stmt = select(InvestorContract).where(
        InvestorContract.id == contract_id,
        InvestorContract.tenant_id == tenant_id
    )
    return (await db.execute(stmt)).scalars().first()


async def render_and_store_investor_contract_pdf(contract_id: int) -> None:
    """Background PDF renderer - uses its own DB session."""
    from app.db.database import AsyncSessionLocal, set_system_rls_context
    from app.services.investor_contract_pdf import generate_investor_contract_pdf

    async with AsyncSessionLocal() as db:
        await set_system_rls_context(db)
        
        # Eager-load vehicle and investor
        stmt = select(InvestorContract).options(
            selectinload(InvestorContract.vehicle).selectinload(Vehicle.owner),
            selectinload(InvestorContract.tenant),
        ).where(InvestorContract.id == contract_id)
        
        result = await db.execute(stmt)
        contract = result.scalars().unique().first()

        if not contract:
            return

        # Skip if already rendered
        if contract.pdf_path and os.path.exists(contract.pdf_path):
            return

        try:
            _ensure_dir()
            pdf_bytes = await generate_investor_contract_pdf(contract, db)
            filepath = os.path.join(CONTRACTS_DIR, f"{contract.contract_number}.pdf")
            with open(filepath, "wb") as f:
                f.write(pdf_bytes)

            contract.pdf_path = filepath
            await db.commit()
            print(f"✅ Investor contract PDF generated (background): {filepath}")
        except Exception as e:
            await db.rollback()
            print(f"❌ Investor contract PDF generation failed: {e}")


async def regenerate_investor_contract(
    contract_id: int,
    tenant_id: int,
    db: AsyncSession
) -> InvestorContract:
    """Delete existing contract PDF and regenerate."""
    contract = await get_investor_contract(db, contract_id, tenant_id)
    
    if not contract:
        raise ValueError(f"Investor contract {contract_id} not found")

    if contract.pdf_path and os.path.exists(contract.pdf_path):
        try:
            os.remove(contract.pdf_path)
        except OSError:
            pass
    
    contract.pdf_path = None
    await db.commit()
    
    # Trigger regeneration
    await render_and_store_investor_contract_pdf(contract_id)
    
    return contract
