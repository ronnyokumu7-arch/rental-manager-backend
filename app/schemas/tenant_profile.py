# app/schemas/tenant_profile.py
from typing import Optional
from pydantic import BaseModel, Field, field_validator

class TenantProfileBase(BaseModel):
    """Maps to TenantProfile SQLAlchemy model.
    Aligned with Frontend Wizard terminology for seamless integration."""
    
    # Identity & Contact
    company_name: Optional[str] = Field(None, max_length=150, description="Legal company name")
    business_location: Optional[str] = Field(None, max_length=255, alias="address", description="Physical office or yard address")
    phone: Optional[str] = Field(None, max_length=30, description="Business contact phone")
    email: Optional[str] = Field(None, max_length=255, description="Business contact email")
    website: Optional[str] = Field(None, max_length=255, description="Company website URL")
    
    # Compliance & Tax
    kra_pin: Optional[str] = Field(None, max_length=20, alias="tax_number", description="KRA PIN for tax invoicing in Kenya")
    
    # Branding & Contracts
    logo_url: Optional[str] = Field(None, max_length=1_000_000, description="URL or data-URL of company logo")
    contract_prefix: Optional[str] = Field(None, max_length=10, description="Auto-generated prefix e.g. T0001")
    contract_terms: Optional[str] = Field(None, description="Default boilerplate terms for rental agreements")
    contract_footer: Optional[str] = Field(None, description="Additional notes or footer for contracts")

    # ✅ NEW: Payment Methods (M-Pesa, Airtel Money & Bank).
    mpesa_paybill: Optional[str] = Field(None, max_length=10, alias="paybill_number", description="M-Pesa PayBill business number")
    mpesa_paybill_account: Optional[str] = Field(None, max_length=50, alias="paybill_account", description="Account clients quote on PayBill")
    mpesa_till: Optional[str] = Field(None, max_length=10, alias="till_number", description="M-Pesa Buy Goods Till number")
    mpesa_pochi: Optional[str] = Field(None, max_length=10, alias="pochi_number", description="M-Pesa Pochi la Biashara number")
    mpesa_number: Optional[str] = Field(None, max_length=20, alias="send_money_number", description="M-Pesa phone number for Send Money")
    airtel_number: Optional[str] = Field(None, max_length=20, description="Airtel Money phone number")
    bank_name: Optional[str] = Field(None, max_length=100, description="Bank for EFT/RTGS transfers")
    bank_account: Optional[str] = Field(None, max_length=34, alias="bank_account_number", description="Bank account number")
    bank_account_name: Optional[str] = Field(None, max_length=150, description="Bank account name; falls back to company_name")

    @field_validator("kra_pin", mode="before")
    @classmethod
    def clean_kra_pin(cls, v):
        if isinstance(v, str):
            cleaned = v.strip().upper()
            return cleaned if cleaned else None
        return v

    class Config:
        populate_by_name = True


class TenantProfileCreate(TenantProfileBase):
    """Used internally by create_tenant route."""
    pass


class TenantProfileUpdate(BaseModel):
    """For updating profile after initial creation."""
    company_name: Optional[str] = Field(None, max_length=150)
    business_location: Optional[str] = Field(None, max_length=255, alias="address")
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=255)
    website: Optional[str] = Field(None, max_length=255)
    kra_pin: Optional[str] = Field(None, max_length=20, alias="tax_number")
    logo_url: Optional[str] = Field(None, max_length=1_000_000)
    contract_prefix: Optional[str] = Field(None, max_length=10)
    contract_terms: Optional[str] = Field(None)
    contract_footer: Optional[str] = Field(None)

    # ✅ NEW: Payment Methods with aliases
    mpesa_paybill: Optional[str] = Field(None, max_length=10, alias="paybill_number")
    mpesa_paybill_account: Optional[str] = Field(None, max_length=50, alias="paybill_account")
    mpesa_till: Optional[str] = Field(None, max_length=10, alias="till_number")
    mpesa_pochi: Optional[str] = Field(None, max_length=10, alias="pochi_number")
    mpesa_number: Optional[str] = Field(None, max_length=20, alias="send_money_number")
    airtel_number: Optional[str] = Field(None, max_length=20)
    bank_name: Optional[str] = Field(None, max_length=100)
    bank_account: Optional[str] = Field(None, max_length=34, alias="bank_account_number")
    bank_account_name: Optional[str] = Field(None, max_length=150)

    @field_validator("kra_pin", mode="before")
    @classmethod
    def clean_kra_pin(cls, v):
        if isinstance(v, str):
            cleaned = v.strip().upper()
            return cleaned if cleaned else None
        return v

    class Config:
        populate_by_name = True


class TenantProfileOut(TenantProfileBase):
    id: int
    tenant_id: int
    model_config = {"from_attributes": True}
