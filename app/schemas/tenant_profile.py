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
    logo_url: Optional[str] = Field(None, max_length=500, description="URL to company logo")
    
    # ✅ FIX: Make optional so frontend doesn't have to send it (backend auto-generates it)
    contract_prefix: Optional[str] = Field(None, max_length=10, description="Auto-generated prefix e.g. T0001")
    
    contract_terms: Optional[str] = Field(None, alias="contract_footer", description="Default boilerplate terms for rental agreements")

    @field_validator("kra_pin", mode="before")
    @classmethod
    def clean_kra_pin(cls, v):
        if isinstance(v, str):
            cleaned = v.strip().upper()
            return cleaned if cleaned else None
        return v

    class Config:
        populate_by_name = True # Allows both 'kra_pin' and 'tax_number' to work

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
    logo_url: Optional[str] = Field(None, max_length=500)
    contract_prefix: Optional[str] = Field(None, max_length=10)
    contract_terms: Optional[str] = Field(None, alias="contract_footer")

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
