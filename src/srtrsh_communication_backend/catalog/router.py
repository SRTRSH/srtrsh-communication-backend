from datetime import date
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
import psycopg

from ..db import get_db_connection
from .schemas import (
    CustomerServiceDetailSchema,
    WorkplaceAvailabilityResponse,
)
from .service import (
    get_customer_availability,
    get_customer_service_detail,
    list_customer_services,
)

router = APIRouter(tags=["Customer Catalog & Availability"])


@router.get(
    "/api/workplaces/{workplace_id}/services",
    response_model=List[CustomerServiceDetailSchema],
)
async def list_customer_services_endpoint(
    workplace_id: UUID,
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await list_customer_services(conn, workplace_id)


@router.get(
    "/api/workplaces/{workplace_id}/services/{service_id}",
    response_model=CustomerServiceDetailSchema,
)
async def get_customer_service_detail_endpoint(
    workplace_id: UUID,
    service_id: UUID,
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await get_customer_service_detail(conn, workplace_id, service_id)


@router.get(
    "/api/workplaces/{workplace_id}/availability",
    response_model=WorkplaceAvailabilityResponse,
)
async def get_customer_availability_endpoint(
    workplace_id: UUID,
    date_from: date = Query(..., description="Start date of the query range"),
    date_to: date = Query(..., description="End date of the query range"),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return await get_customer_availability(
        conn,
        workplace_id,
        date_from=date_from,
        date_to=date_to,
    )
