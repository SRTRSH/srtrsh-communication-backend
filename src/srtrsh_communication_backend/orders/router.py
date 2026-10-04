from datetime import date
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
import psycopg

from ..db import get_db_connection
from .schemas import (
    CreateOrderRequest,
    CustomerProposalRequest,
    CustomerAcceptanceRequest,
    CustomerCancellationRequest,
    OrderDetailSchema,
)
from .service import (
    create_customer_order,
    customer_proposal,
    customer_acceptance,
    customer_cancel_order,
    get_order_by_id,
    get_customer_orders,
    get_customer_appointments,
)

router = APIRouter(prefix="/api/orders", tags=["Customer Orders"])


@router.post("", response_model=OrderDetailSchema, status_code=201)
async def create_order_endpoint(
    req: CreateOrderRequest,
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await create_customer_order(conn, req)


@router.get("/{order_id}", response_model=OrderDetailSchema)
async def get_order_endpoint(
    order_id: UUID,
    customer_id: Optional[UUID] = Query(None, description="Optional customer ID for access control"),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await get_order_by_id(conn, order_id, customer_id=customer_id)


@router.get("/customer/{customer_id}", response_model=List[OrderDetailSchema])
async def list_customer_orders_endpoint(
    customer_id: UUID,
    status: Optional[str] = Query(None, description="Filter orders by status"),
    date_from: Optional[date] = Query(None, description="Start date of order window"),
    date_to: Optional[date] = Query(None, description="End date of order window"),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await get_customer_orders(
        conn,
        customer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/customer/{customer_id}/appointments", response_model=List[OrderDetailSchema])
async def list_customer_appointments_endpoint(
    customer_id: UUID,
    date_from: Optional[date] = Query(None, description="Start date of appointments window"),
    date_to: Optional[date] = Query(None, description="End date of appointments window"),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await get_customer_appointments(
        conn,
        customer_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("/{order_id}/proposals", response_model=OrderDetailSchema)
async def customer_proposal_endpoint(
    order_id: UUID,
    req: CustomerProposalRequest,
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await customer_proposal(conn, order_id, req)


@router.post("/{order_id}/accept", response_model=OrderDetailSchema)
async def customer_acceptance_endpoint(
    order_id: UUID,
    req: CustomerAcceptanceRequest,
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await customer_acceptance(conn, order_id, req)


@router.post("/{order_id}/cancel", response_model=OrderDetailSchema)
async def customer_cancel_endpoint(
    order_id: UUID,
    req: CustomerCancellationRequest,
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await customer_cancel_order(conn, order_id, req)
