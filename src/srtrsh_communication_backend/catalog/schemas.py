from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class CustomerServiceDetailSchema(BaseModel):
    id: UUID
    workplace_id: UUID
    name: str
    description: Optional[str]
    price: Decimal
    currency_code: str
    duration_atp: int
    duration_minutes: int
    status: str
    created_at: datetime


class TimeIntervalSchema(BaseModel):
    start_time: datetime
    end_time: datetime


class DayAvailabilitySchema(BaseModel):
    date: date
    free_intervals: List[TimeIntervalSchema]


class WorkplaceAvailabilityResponse(BaseModel):
    workplace_id: UUID
    date_from: date
    date_to: date
    days: List[DayAvailabilitySchema]
