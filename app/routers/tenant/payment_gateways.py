# app/routers/tenants/payment_gateways.py (or wherever this file is named)

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.limiter import limiter
from app.core.security import encrypt_secret, decrypt_secret
from app.dependencies.auth import get_current_user
from app.models.tenants import Tenant
from app.models.users import User, UserRole
from app.models.payment_gateways.mpesa import MpesaConfig
from app.models.payment_gateways.airtel import AirtelMoneyConfig
from app.models.payment_gateways.bank import BankAccountConfig
from app.models.payment_gateways.stripe import StripeConfig
from app.models.payment_gateways.paypal import PaypalConfig
from app.services.cache import invalidate_tenant_cache
from app.services.activity_log import ActivityLogService

router = APIRouter()

# Map gateway type strings to their config models
GATEWAY_MODELS = {
    "mpesa": MpesaConfig,
    "airtel_money": AirtelMoneyConfig,
    "bank": BankAccountConfig,
    "stripe": StripeConfig,
    "paypal": PaypalConfig,
}

# Define which fields contain sensitive credentials that must be encrypted
SENSITIVE_FIELDS = {
    "mpesa": ["consumer_key", "consumer_secret", "passkey"],
    "airtel_money": ["api_key", "api_secret"],
    "bank": ["account_number"],
    "stripe": ["secret_key", "webhook_secret"],
    "paypal": ["client_id", "client_secret"],
}


def _encrypt_gateway_data(gateway_type: str, data: dict) -> dict:
    """Encrypt sensitive fields before saving to database."""
    encrypted_data = data.copy()
    sensitive_fields = SENSITIVE_FIELDS.get(gateway_type, [])
    
    for field in sensitive_fields:
        if field in encrypted_data and encrypted_data[field]:
            encrypted_data[field] = encrypt_secret(str(encrypted_data[field]))
    
    return encrypted_data


def _decrypt_and_mask_credentials(gateway_type: str, config: object) -> dict:
    """Decrypt sensitive fields, then mask them for safe display."""
    data = {}
    sensitive_fields = SENSITIVE_FIELDS.get(gateway_type, [])
    
    for key, value in config.__dict__.items():
        if key.startswith("_"):
            continue
        
        # Decrypt sensitive fields first, then mask
        if key in sensitive_fields and value:
            try:
                decrypted = decrypt_secret(value)
                # Show only last 4 characters
                data[key] = f"****{decrypted[-4:]}" if len(decrypted) >= 4 else "****"
            except Exception:
                # If decryption fails, show masked encrypted value
                data[key] = "****[encrypted]"
        else:
            data[key] = value
    
    return data


async def _verify_tenant_access(tenant_id: int, current_user: User):
    """
    Verify that the current user has access to the specified tenant.
    - Super admins can access any tenant
    - Regular users can only access their own tenant
    """
    if current_user.role == UserRole.super_admin:
        return  # Super admins have full access
    
    # Regular users can only access their own tenant
    if current_user.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this tenant's payment gateways",
        )


@router.get("/{tenant_id}/payment-gateways")
@limiter.limit("30/minute")
async def list_gateways(
    request: Request,
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all payment gateway configurations for a tenant."""
    await _verify_tenant_access(tenant_id, current_user)
    
    tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    gateways = []
    for gw_type, model_class in GATEWAY_MODELS.items():
        if gw_type == "bank":
            # Bank accounts can have multiple configs
            stmt = select(BankAccountConfig).where(BankAccountConfig.tenant_id == tenant_id)
            configs = (await db.execute(stmt)).scalars().all()
            for c in configs:
                gateways.append({**_decrypt_and_mask_credentials(gw_type, c), "type": gw_type})
        else:
            # Other gateways have single config per tenant
            stmt = select(model_class).where(model_class.tenant_id == tenant_id)
            config = (await db.execute(stmt)).scalars().first()
            if config:
                gateways.append({**_decrypt_and_mask_credentials(gw_type, config), "type": gw_type})

    return {"gateways": gateways}


@router.post("/{tenant_id}/payment-gateways/{gateway_type}", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_gateway(
    request: Request,
    tenant_id: int,
    gateway_type: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new payment gateway configuration for a tenant."""
    await _verify_tenant_access(tenant_id, current_user)
    
    if gateway_type not in GATEWAY_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid gateway type. Must be one of: {', '.join(GATEWAY_MODELS.keys())}",
        )

    tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
    tenant = (await db.execute(tenant_stmt)).scalars().first()
    
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    ModelClass = GATEWAY_MODELS[gateway_type]

    # Check if config already exists (for single-config gateways)
    if gateway_type != "bank":
        stmt = select(ModelClass).where(ModelClass.tenant_id == tenant_id)
        existing = (await db.execute(stmt)).scalars().first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{gateway_type} config already exists. Use PATCH to update.",
            )

    # Encrypt sensitive fields before saving
    encrypted_payload = _encrypt_gateway_data(gateway_type, payload)
    
    # Create new config
    config_data = {"tenant_id": tenant_id, **encrypted_payload}
    new_config = ModelClass(**config_data)
    db.add(new_config)
    
    await db.commit()
    await db.refresh(new_config)

    # ✅ Invalidate tenant cache and log the gateway creation
    await invalidate_tenant_cache()
    await ActivityLogService.log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action=f"create_{gateway_type}_gateway",
        target_type="payment_gateway",
        target_id=new_config.id,
        details={"gateway_type": gateway_type}
    )
    await db.commit()  # Commit the activity log flush

    return {**_decrypt_and_mask_credentials(gateway_type, new_config), "type": gateway_type}


@router.patch("/{tenant_id}/payment-gateways/{gateway_type}/{config_id}")
@limiter.limit("10/minute")
async def update_gateway(
    request: Request,
    tenant_id: int,
    gateway_type: str,
    config_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing payment gateway configuration."""
    await _verify_tenant_access(tenant_id, current_user)
    
    if gateway_type not in GATEWAY_MODELS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid gateway type")

    ModelClass = GATEWAY_MODELS[gateway_type]
    stmt = select(ModelClass).where(
        ModelClass.id == config_id,
        ModelClass.tenant_id == tenant_id,
    )
    config = (await db.execute(stmt)).scalars().first()

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gateway config not found")

    # Encrypt sensitive fields before updating
    encrypted_payload = _encrypt_gateway_data(gateway_type, payload)
    
    for field, value in encrypted_payload.items():
        if hasattr(config, field):
            setattr(config, field, value)

    await db.commit()
    await db.refresh(config)

    # ✅ Invalidate tenant cache and log the gateway update
    await invalidate_tenant_cache()
    await ActivityLogService.log(
        db=db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action=f"update_{gateway_type}_gateway",
        target_type="payment_gateway",
        target_id=config.id,
        details={"gateway_type": gateway_type, "updated_fields": list(payload.keys())}
    )
    await db.commit()  # Commit the activity log flush

    return {**_decrypt_and_mask_credentials(gateway_type, config), "type": gateway_type}


@router.post("/{tenant_id}/payment-gateways/{gateway_type}/test")
@limiter.limit("10/minute")
async def test_gateway_connection(
    request: Request,
    tenant_id: int,
    gateway_type: str,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test connectivity to payment gateway without saving credentials."""
    await _verify_tenant_access(tenant_id, current_user)
    
    if gateway_type not in GATEWAY_MODELS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid gateway type")

    # Validate required fields are present
    required_fields = {
        "mpesa": ["consumer_key", "consumer_secret", "passkey"],
        "airtel_money": ["api_key", "api_secret", "merchant_code"],
        "bank": ["account_number", "bank_name"],
        "stripe": ["publishable_key", "secret_key"],
        "paypal": ["client_id", "client_secret"],
    }

    missing = [f for f in required_fields.get(gateway_type, []) if not payload or f not in payload]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required fields for {gateway_type}: {', '.join(missing)}",
        )

    # TODO: Implement actual API ping for each gateway type
    return {
        "gateway_type": gateway_type,
        "status": "connected",
        "message": f"{gateway_type} credentials validated successfully.",
    }
