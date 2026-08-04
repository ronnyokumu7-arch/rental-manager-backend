from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService

class ContractActivityLogger:
    @staticmethod
    async def on_generated(db: AsyncSession, tenant_id: int, user_id: int, contract) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="generate_contract", target_type="contract", target_id=contract.id, details={"contract_number": contract.contract_number})

    @staticmethod
    async def on_signed(db: AsyncSession, tenant_id: int, user_id: int, contract, signer: str = "client") -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="sign_contract", target_type="contract", target_id=contract.id, details={"contract_number": contract.contract_number, "signed_by": signer})

    @staticmethod
    async def on_voided(db: AsyncSession, tenant_id: int, user_id: int, contract) -> None:
        await ActivityLogService.log(db=db, tenant_id=tenant_id, user_id=user_id, action="void_contract", target_type="contract", target_id=contract.id, details={"contract_number": contract.contract_number})
