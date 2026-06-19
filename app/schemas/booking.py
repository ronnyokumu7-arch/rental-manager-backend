from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.bookings import BookingStatus


class BookingBase(BaseModel):
    client_id: int
    vehicle_id: int
    start_date: date
    end_date: date
    total_amount: int = Field(gt=0)
    currency_code: str = Field(default="KES", min_length=3, max_length=3)

    @model_validator(mode="after")
    def end_date_must_be_after_start_date(self) -> "BookingBase":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class BookingCreate(BookingBase):
    pass


class BookingUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    total_amount: Optional[int] = Field(default=None, gt=0)
    currency_code: Optional[str] = Field(default=None, min_length=3, max_length=3)
    status: Optional[BookingStatus] = None

    @model_validator(mode="after")
    def end_date_must_be_after_start_date(self) -> "BookingUpdate":
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class BookingOut(BaseModel):
    id: int
    tenant_id: int
    client_id: int
    vehicle_id: int
    start_date: date
    end_date: date
    total_amount: int
    currency_code: str
    status: BookingStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}