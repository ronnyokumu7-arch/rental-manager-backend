from sqlalchemy.ext.asyncio import AsyncSession
from .service import ActivityLogService


class ContractActivityLogger:
    """Logger for Contract lifecycle events."""

    @staticmethod
    async def on_generated(db: AsyncSession, tenant_id: int, user_id: int, contract) -> None:
        """
        Log a contract generation event.
        """
        summary = {
            "contract_number": contract.contract_number,
            "client_name": getattr(contract.client, "full_name", None) if contract.client else None,
            "client_phone": getattr(contract.client, "phone", None) if contract.client else None,
            "booking_number": contract.booking_number if hasattr(contract, "booking_number") else None,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="generate_contract",
            label="Contract Generated",
            target_type="contract",
            target_id=contract.id,
            summary=summary,
            details={
                "contract_number": contract.contract_number,
                "client_name": summary["client_name"],
            },
            priority=2,  # Normal
        )

    @staticmethod
    async def on_signed(db: AsyncSession, tenant_id: int, user_id: int, contract, signer: str = "client") -> None:
        """
        Log a contract signing event.
        
        ✅ CRITICAL: Signed contracts are High Priority (Business Win / Revenue).
        """
        summary = {
            "contract_number": contract.contract_number,
            "client_name": getattr(contract.client, "full_name", None) if contract.client else None,
            "client_phone": getattr(contract.client, "phone", None) if contract.client else None,
            "signed_by": signer,
            "booking_number": contract.booking_number if hasattr(contract, "booking_number") else None,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="sign_contract",
            label="Contract Signed",
            target_type="contract",
            target_id=contract.id,
            summary=summary,
            details={
                "contract_number": contract.contract_number,
                "signed_by": signer,
            },
            priority=3,  # High (Business Win)
        )

    @staticmethod
    async def on_voided(db: AsyncSession, tenant_id: int, user_id: int, contract) -> None:
        """
        Log a contract void event.
        """
        summary = {
            "contract_number": contract.contract_number,
            "client_name": getattr(contract.client, "full_name", None) if contract.client else None,
            "client_phone": getattr(contract.client, "phone", None) if contract.client else None,
        }

        await ActivityLogService.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="void_contract",
            label="Contract Voided",
            target_type="contract",
            target_id=contract.id,
            summary=summary,
            details={
                "contract_number": contract.contract_number,
            },
            priority=3,  # High (Lost Business / Compliance)
        )
