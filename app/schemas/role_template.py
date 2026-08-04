from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.permissions import ALL_PERMISSION_KEYS


class RoleTemplateBase(BaseModel):
    """Shared fields for role template schemas."""
    job_title: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Job title this template applies to (e.g., 'Driver', 'Accountant')",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional description of the template's purpose",
    )
    permissions: List[str] = Field(
        default_factory=list,
        description="List of permission keys assigned to this role",
    )

    @field_validator("job_title")
    @classmethod
    def normalize_job_title(cls, v: str) -> str:
        """Normalize job title: strip whitespace and convert to title case."""
        return v.strip().title()

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: List[str]) -> List[str]:
        """
        ✅ SECURITY: Validate each permission key against the master list.
        Also checks for duplicates to prevent accidental misconfiguration.
        """
        if not v:
            return v  # Empty list is valid (no permissions)
        
        # Check for duplicates
        if len(v) != len(set(v)):
            duplicates = [p for p in v if v.count(p) > 1]
            raise ValueError(f"Duplicate permissions found: {set(duplicates)}")
        
        # Validate each permission
        for perm in v:
            if perm not in ALL_PERMISSION_KEYS:
                raise ValueError(f"Invalid permission key: {perm}")
        
        return v


class RoleTemplateCreate(RoleTemplateBase):
    """Payload for creating a new role template."""
    pass


class RoleTemplateUpdate(BaseModel):
    """
    Payload for updating a role template.
    All fields are optional — only provided fields are updated.
    """
    job_title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="New job title for this template",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="New description for this template",
    )
    permissions: Optional[List[str]] = Field(
        default=None,
        description="New list of permission keys",
    )

    @field_validator("job_title")
    @classmethod
    def normalize_job_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip().title()

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        
        if len(v) != len(set(v)):
            duplicates = [p for p in v if v.count(p) > 1]
            raise ValueError(f"Duplicate permissions found: {set(duplicates)}")
        
        for perm in v:
            if perm not in ALL_PERMISSION_KEYS:
                raise ValueError(f"Invalid permission key: {perm}")
        
        return v


class RoleTemplateOut(BaseModel):
    """Output schema for role templates."""
    id: int
    tenant_id: int
    job_title: str
    description: Optional[str] = None
    permissions: List[str]

    model_config = {"from_attributes": True}
