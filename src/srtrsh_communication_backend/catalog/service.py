import calendar
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Tuple
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException

from .schemas import (
    CustomerServiceDetailSchema,
    DayAvailabilitySchema,
    TimeIntervalSchema,
    WorkplaceAvailabilityResponse,
)


def add_months(sourcedate: date, months: int) -> date:
    """Adds a number of months to a date, pinning to the last day of the month if necessary."""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _subtract_intervals(
    base_intervals: List[Tuple[datetime, datetime]],
    occupied_intervals: List[Tuple[datetime, datetime]],
) -> List[Tuple[datetime, datetime]]:
    """Subtracts occupied intervals from base intervals, returning remaining free intervals."""
    current = list(base_intervals)
    for occ_start, occ_end in sorted(occupied_intervals, key=lambda x: x[0]):
        next_intervals = []
        for free_start, free_end in current:
            if occ_end <= free_start or occ_start >= free_end:
                next_intervals.append((free_start, free_end))
            else:
                if occ_start > free_start:
                    next_intervals.append((free_start, occ_start))
                if occ_end < free_end:
                    next_intervals.append((occ_end, free_end))
        current = [iv for iv in next_intervals if iv[1] > iv[0]]
    return current


async def list_customer_services(
    conn: psycopg.AsyncConnection,
    workplace_id: UUID,
) -> List[CustomerServiceDetailSchema]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, status, atp_duration_minutes FROM workplaces WHERE id = %s",
            (workplace_id,),
        )
        wp = await cur.fetchone()
        if not wp or wp["status"] == "BLOCKED":
            raise HTTPException(status_code=404, detail="Workplace not found")

        # Canonical rule: Customers only see ACTIVE services with admin_review_state = NORMAL.
        # BLOCKED and SUSPECTED services are excluded from active operational listings.
        await cur.execute(
            """
            SELECT s.id, s.workplace_id, s.name, s.description, s.price, s.currency_code,
                   s.duration_atp, (s.duration_atp * w.atp_duration_minutes) AS duration_minutes,
                   s.status, s.created_at
            FROM services s
            JOIN workplaces w ON s.workplace_id = w.id
            WHERE s.workplace_id = %s
              AND s.status = 'ACTIVE'
              AND s.admin_review_state = 'NORMAL'
            ORDER BY s.name ASC
            """,
            (workplace_id,),
        )
        rows = await cur.fetchall()

    return [CustomerServiceDetailSchema(**r) for r in rows]


async def get_customer_service_detail(
    conn: psycopg.AsyncConnection,
    workplace_id: UUID,
    service_id: UUID,
) -> CustomerServiceDetailSchema:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT s.id, s.workplace_id, s.name, s.description, s.price, s.currency_code,
                   s.duration_atp, (s.duration_atp * w.atp_duration_minutes) AS duration_minutes,
                   s.status, s.created_at
            FROM services s
            JOIN workplaces w ON s.workplace_id = w.id
            WHERE s.id = %s
              AND s.workplace_id = %s
              AND s.status = 'ACTIVE'
              AND s.admin_review_state = 'NORMAL'
            """,
            (service_id, workplace_id),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Service not found or unavailable")

    return CustomerServiceDetailSchema(**row)


async def get_customer_availability(
    conn: psycopg.AsyncConnection,
    workplace_id: UUID,
    date_from: date,
    date_to: date,
) -> WorkplaceAvailabilityResponse:
    if date_to < date_from:
        raise HTTPException(status_code=400, detail="date_to cannot be earlier than date_from")

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT w.id, w.status, w.business_domain_id,
                   bd.future_request_window_months, bd.max_request_duration_months
            FROM workplaces w
            JOIN business_domains bd ON w.business_domain_id = bd.id
            WHERE w.id = %s
            """,
            (workplace_id,),
        )
        wp = await cur.fetchone()
        if not wp or wp["status"] == "BLOCKED":
            raise HTTPException(status_code=404, detail="Workplace not found")

        # Validate Customer Request Period parameters
        today = datetime.now(timezone.utc).date()
        max_future_date = add_months(today, wp["future_request_window_months"])
        if date_to > max_future_date:
            raise HTTPException(
                status_code=400,
                detail=f"Requested date_to exceeds the future request window of {wp['future_request_window_months']} month(s)",
            )

        max_allowed_date_to = add_months(date_from, wp["max_request_duration_months"])
        if date_to > max_allowed_date_to:
            raise HTTPException(
                status_code=400,
                detail=f"Requested date range exceeds the maximum allowed request duration of {wp['max_request_duration_months']} month(s)",
            )

        # Fetch working periods
        await cur.execute(
            """
            SELECT day_of_week, start_time, end_time
            FROM workplace_working_periods
            WHERE workplace_id = %s
            ORDER BY day_of_week ASC, start_time ASC
            """,
            (workplace_id,),
        )
        wp_rows = await cur.fetchall()

        # Fetch confirmed appointments
        query_start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        query_end = datetime.combine(date_to + timedelta(days=2), time.max, tzinfo=timezone.utc)

        await cur.execute(
            """
            SELECT start_time, end_time
            FROM orders
            WHERE workplace_id = %s
              AND status = 'APPOINTMENT'
              AND start_time IS NOT NULL
              AND end_time IS NOT NULL
              AND end_time > %s
              AND start_time < %s
            ORDER BY start_time ASC
            """,
            (workplace_id, query_start, query_end),
        )
        appt_rows = await cur.fetchall()

    periods_by_dow = {}
    for r in wp_rows:
        periods_by_dow.setdefault(r["day_of_week"], []).append(r)

    appointments: List[Tuple[datetime, datetime]] = []
    for appt in appt_rows:
        st = appt["start_time"]
        et = appt["end_time"]
        if st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
        if et.tzinfo is None:
            et = et.replace(tzinfo=timezone.utc)
        appointments.append((st, et))

    days: List[DayAvailabilitySchema] = []
    curr = date_from
    while curr <= date_to:
        iso_dow = curr.isoweekday()
        day_periods = periods_by_dow.get(iso_dow, [])
        day_free_intervals: List[Tuple[datetime, datetime]] = []

        for p in day_periods:
            p_start = datetime.combine(curr, p["start_time"], tzinfo=timezone.utc)
            if p["end_time"] <= p["start_time"]:
                p_end = datetime.combine(curr + timedelta(days=1), p["end_time"], tzinfo=timezone.utc)
            else:
                p_end = datetime.combine(curr, p["end_time"], tzinfo=timezone.utc)

            overlapping_appts = [
                (a_st, a_et) for (a_st, a_et) in appointments
                if a_st < p_end and a_et > p_start
            ]

            free_for_period = _subtract_intervals([(p_start, p_end)], overlapping_appts)
            day_free_intervals.extend(free_for_period)

        day_free_intervals.sort(key=lambda x: x[0])
        days.append(
            DayAvailabilitySchema(
                date=curr,
                free_intervals=[
                    TimeIntervalSchema(start_time=iv[0], end_time=iv[1])
                    for iv in day_free_intervals
                ],
            )
        )
        curr += timedelta(days=1)

    return WorkplaceAvailabilityResponse(
        workplace_id=workplace_id,
        date_from=date_from,
        date_to=date_to,
        days=days,
    )
