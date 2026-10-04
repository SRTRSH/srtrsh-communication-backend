from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class CreateOrderItemRequest(BaseModel):
    service_id: UUID
    quantity: int = Field(default=1, ge=1)


class CreateOrderRequest(BaseModel):
    customer_id: UUID
    workplace_id: UUID
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    items: List[CreateOrderItemRequest] = Field(min_length=1)


class CustomerProposalRequest(BaseModel):
    customer_id: UUID
    start_time: datetime
    end_time: datetime


class CustomerAcceptanceRequest(BaseModel):
    customer_id: UUID
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class CustomerCancellationRequest(BaseModel):
    customer_id: UUID


class OrderItemSnapshotSchema(BaseModel):
    id: UUID
    order_id: UUID
    service_id: Optional[UUID] = None
    name: str
    price: Decimal
    currency_code: str
    duration_atp: int
    quantity: int
    created_at: datetime


class OrderActionSchema(BaseModel):
    id: UUID
    order_id: UUID
    type: str  # PROPOSAL, ACCEPTANCE, CANCELLATION
    initiator: str  # CUSTOMER, MASTER
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    created_at: datetime


class OrderDetailSchema(BaseModel):
    id: UUID
    customer_id: UUID
    workplace_id: UUID
    initiator: str
    status: str  # ORDER, PROPOSAL, ACCEPTANCE, APPOINTMENT, VOID
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemSnapshotSchema] = Field(default_factory=list)
    actions: List[OrderActionSchema] = Field(default_factory=list)
