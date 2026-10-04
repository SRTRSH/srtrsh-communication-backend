from datetime import date, datetime, time, timezone
from typing import List, Optional
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException

from .schemas import (
    CreateOrderRequest,
    CustomerProposalRequest,
    CustomerAcceptanceRequest,
    CustomerCancellationRequest,
    OrderDetailSchema,
    OrderItemSnapshotSchema,
    OrderActionSchema,
)


async def get_order_by_id(
    conn: psycopg.AsyncConnection,
    order_id: UUID,
    customer_id: Optional[UUID] = None,
) -> OrderDetailSchema:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT id, customer_id, workplace_id, initiator, status, start_time, end_time, created_at, updated_at
            FROM orders
            WHERE id = %s
            """,
            (order_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")

        if customer_id is not None and row["customer_id"] != customer_id:
            raise HTTPException(status_code=403, detail="Unauthorized access to another customer's order")

        # Fetch snapshot items
        await cur.execute(
            """
            SELECT id, order_id, service_id, name, price, currency_code, duration_atp, quantity, created_at
            FROM order_items
            WHERE order_id = %s
            ORDER BY created_at ASC
            """,
            (order_id,),
        )
        items_rows = await cur.fetchall()

        # Fetch actions history
        await cur.execute(
            """
            SELECT id, order_id, type, initiator, start_time, end_time, created_at
            FROM order_actions
            WHERE order_id = %s
            ORDER BY created_at ASC
            """,
            (order_id,),
        )
        actions_rows = await cur.fetchall()

    return OrderDetailSchema(
        id=row["id"],
        customer_id=row["customer_id"],
        workplace_id=row["workplace_id"],
        initiator=row["initiator"],
        status=row["status"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        items=[OrderItemSnapshotSchema(**it) for it in items_rows],
        actions=[OrderActionSchema(**act) for act in actions_rows],
    )


async def get_customer_orders(
    conn: psycopg.AsyncConnection,
    customer_id: UUID,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[OrderDetailSchema]:
    async with conn.cursor(row_factory=dict_row) as cur:
        # Validate Customer exists
        await cur.execute("SELECT id FROM customers WHERE id = %s", (customer_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        query = "SELECT id FROM orders WHERE customer_id = %s"
        params = [customer_id]

        if status:
            query += " AND status = %s"
            params.append(status.upper())

        if date_from:
            dt_from = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
            query += " AND (end_time >= %s OR (end_time IS NULL AND start_time >= %s))"
            params.extend([dt_from, dt_from])

        if date_to:
            dt_to = datetime.combine(date_to, time.max, tzinfo=timezone.utc)
            query += " AND (start_time <= %s OR (start_time IS NULL AND end_time <= %s))"
            params.extend([dt_to, dt_to])

        query += " ORDER BY created_at DESC"

        await cur.execute(query, tuple(params))
        rows = await cur.fetchall()

    results = []
    for r in rows:
        order = await get_order_by_id(conn, r["id"], customer_id=customer_id)
        results.append(order)
    return results


async def get_customer_appointments(
    conn: psycopg.AsyncConnection,
    customer_id: UUID,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[OrderDetailSchema]:
    return await get_customer_orders(
        conn,
        customer_id=customer_id,
        status="APPOINTMENT",
        date_from=date_from,
        date_to=date_to,
    )


async def create_customer_order(
    conn: psycopg.AsyncConnection,
    req: CreateOrderRequest,
) -> OrderDetailSchema:
    if req.start_time and req.end_time and req.end_time <= req.start_time:
        raise HTTPException(status_code=400, detail="end_time must be greater than start_time")

    if not req.items:
        raise HTTPException(status_code=400, detail="Order must contain at least one service item")

    async with conn.cursor(row_factory=dict_row) as cur:
        # Validate Customer exists
        await cur.execute("SELECT id FROM customers WHERE id = %s", (req.customer_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Customer {req.customer_id} not found")

        # Validate Workplace exists and is active
        await cur.execute("SELECT id, master_id, status FROM workplaces WHERE id = %s", (req.workplace_id,))
        wp = await cur.fetchone()
        if not wp:
            raise HTTPException(status_code=404, detail=f"Workplace {req.workplace_id} not found")
        if wp["status"] != "ACTIVE":
            raise HTTPException(status_code=400, detail="Workplace is not active")

        # Validate and prepare service snapshots
        snapshots = []
        for it in req.items:
            if it.quantity < 1:
                raise HTTPException(status_code=400, detail="Service item quantity must be at least 1")

            await cur.execute(
                """
                SELECT id, name, price, currency_code, duration_atp, status, admin_review_state
                FROM services
                WHERE id = %s AND workplace_id = %s
                """,
                (it.service_id, req.workplace_id),
            )
            svc = await cur.fetchone()
            if not svc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Service {it.service_id} not found in workplace {req.workplace_id}",
                )
            if svc["status"] != "ACTIVE":
                raise HTTPException(status_code=400, detail=f"Service {it.service_id} is not active")
            if svc["admin_review_state"] == "SUSPECTED":
                raise HTTPException(
                    status_code=400,
                    detail=f"Service {it.service_id} is under SUSPECTED review and unavailable for new Activities",
                )

            snapshots.append(
                {
                    "service_id": svc["id"],
                    "name": svc["name"],
                    "price": svc["price"],
                    "currency_code": svc["currency_code"],
                    "duration_atp": svc["duration_atp"],
                    "quantity": it.quantity,
                }
            )

        order_id = uuid4()
        # Insert Order with status = ORDER, initiator = CUSTOMER
        await cur.execute(
            """
            INSERT INTO orders (id, customer_id, workplace_id, initiator, status, start_time, end_time, created_at, updated_at)
            VALUES (%s, %s, %s, 'CUSTOMER', 'ORDER', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (order_id, req.customer_id, req.workplace_id, req.start_time, req.end_time),
        )

        # Insert immutable order_items snapshots
        for sn in snapshots:
            await cur.execute(
                """
                INSERT INTO order_items (id, order_id, service_id, name, price, currency_code, duration_atp, quantity, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    uuid4(),
                    order_id,
                    sn["service_id"],
                    sn["name"],
                    sn["price"],
                    sn["currency_code"],
                    sn["duration_atp"],
                    sn["quantity"],
                ),
            )

        # Idempotently record master-customer relationship
        await cur.execute(
            """
            INSERT INTO master_customers (master_id, customer_id)
            VALUES (%s, %s)
            ON CONFLICT (master_id, customer_id) DO NOTHING
            """,
            (wp["master_id"], req.customer_id),
        )

    await conn.commit()
    return await get_order_by_id(conn, order_id)


async def customer_proposal(
    conn: psycopg.AsyncConnection,
    order_id: UUID,
    req: CustomerProposalRequest,
) -> OrderDetailSchema:
    if req.end_time <= req.start_time:
        raise HTTPException(status_code=400, detail="end_time must be greater than start_time")

    now = datetime.now(timezone.utc)

    async with conn.cursor(row_factory=dict_row) as cur:
        # Row-level lock to protect concurrent mutations
        await cur.execute(
            """
            SELECT o.id, o.customer_id, o.status, o.end_time, w.master_id
            FROM orders o
            JOIN workplaces w ON o.workplace_id = w.id
            WHERE o.id = %s
            FOR UPDATE OF o
            """,
            (order_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")

        # Authorization: verify customer ownership
        if row["customer_id"] != req.customer_id:
            raise HTTPException(status_code=403, detail="Unauthorized access to another customer's order")

        status = row["status"]
        if status == "VOID":
            raise HTTPException(status_code=400, detail="Cannot propose time for cancelled (VOID) order")

        if status == "APPOINTMENT":
            if row["end_time"] and row["end_time"] <= now:
                raise HTTPException(status_code=400, detail="Appointment has expired and is immutable")
            raise HTTPException(
                status_code=400,
                detail="Order is already confirmed as APPOINTMENT. New proposals are not allowed",
            )

        if status not in ("ORDER", "PROPOSAL", "ACCEPTANCE"):
            raise HTTPException(status_code=400, detail=f"Cannot propose time in current status: {status}")

        # Record PROPOSAL action
        await cur.execute(
            """
            INSERT INTO order_actions (id, order_id, type, initiator, start_time, end_time, created_at)
            VALUES (%s, %s, 'PROPOSAL', 'CUSTOMER', %s, %s, CURRENT_TIMESTAMP)
            """,
            (uuid4(), order_id, req.start_time, req.end_time),
        )

        # Update order current state
        await cur.execute(
            """
            UPDATE orders
            SET status = 'PROPOSAL',
                start_time = %s,
                end_time = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (req.start_time, req.end_time, order_id),
        )

        # Idempotently record master-customer relationship
        await cur.execute(
            """
            INSERT INTO master_customers (master_id, customer_id)
            VALUES (%s, %s)
            ON CONFLICT (master_id, customer_id) DO NOTHING
            """,
            (row["master_id"], req.customer_id),
        )

    await conn.commit()
    return await get_order_by_id(conn, order_id)


async def customer_acceptance(
    conn: psycopg.AsyncConnection,
    order_id: UUID,
    req: CustomerAcceptanceRequest,
) -> OrderDetailSchema:
    now = datetime.now(timezone.utc)

    async with conn.cursor(row_factory=dict_row) as cur:
        # Row-level lock
        await cur.execute(
            """
            SELECT o.id, o.customer_id, o.status, o.start_time, o.end_time, w.master_id
            FROM orders o
            JOIN workplaces w ON o.workplace_id = w.id
            WHERE o.id = %s
            FOR UPDATE OF o
            """,
            (order_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")

        # Authorization: verify customer ownership
        if row["customer_id"] != req.customer_id:
            raise HTTPException(status_code=403, detail="Unauthorized access to another customer's order")

        status = row["status"]
        if status == "VOID":
            raise HTTPException(status_code=400, detail="Cannot accept cancelled (VOID) order")

        if status == "APPOINTMENT":
            if row["end_time"] and row["end_time"] <= now:
                raise HTTPException(status_code=400, detail="Appointment has expired and is immutable")
            raise HTTPException(status_code=400, detail="Order is already confirmed as APPOINTMENT")

        if status not in ("ORDER", "PROPOSAL"):
            raise HTTPException(status_code=400, detail=f"Cannot perform customer acceptance in status: {status}")

        start_time = req.start_time or row["start_time"]
        end_time = req.end_time or row["end_time"]

        if start_time and end_time and end_time <= start_time:
            raise HTTPException(status_code=400, detail="end_time must be greater than start_time")

        # Record ACCEPTANCE action by CUSTOMER
        await cur.execute(
            """
            INSERT INTO order_actions (id, order_id, type, initiator, start_time, end_time, created_at)
            VALUES (%s, %s, 'ACCEPTANCE', 'CUSTOMER', %s, %s, CURRENT_TIMESTAMP)
            """,
            (uuid4(), order_id, start_time, end_time),
        )

        # Update order current state to ACCEPTANCE (Do NOT transition to APPOINTMENT)
        await cur.execute(
            """
            UPDATE orders
            SET status = 'ACCEPTANCE',
                start_time = %s,
                end_time = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (start_time, end_time, order_id),
        )

        # Idempotently record master-customer relationship
        await cur.execute(
            """
            INSERT INTO master_customers (master_id, customer_id)
            VALUES (%s, %s)
            ON CONFLICT (master_id, customer_id) DO NOTHING
            """,
            (row["master_id"], req.customer_id),
        )

    await conn.commit()
    return await get_order_by_id(conn, order_id)


async def customer_cancel_order(
    conn: psycopg.AsyncConnection,
    order_id: UUID,
    req: CustomerCancellationRequest,
) -> OrderDetailSchema:
    now = datetime.now(timezone.utc)

    async with conn.cursor(row_factory=dict_row) as cur:
        # Row-level lock
        await cur.execute(
            """
            SELECT id, customer_id, status, end_time
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")

        # Authorization: verify customer ownership
        if row["customer_id"] != req.customer_id:
            raise HTTPException(status_code=403, detail="Unauthorized access to another customer's order")

        status = row["status"]
        if status == "VOID":
            raise HTTPException(status_code=400, detail="Order is already cancelled (VOID)")

        if status == "APPOINTMENT":
            if row["end_time"] and row["end_time"] <= now:
                raise HTTPException(status_code=400, detail="Appointment has expired and is immutable")
            # Confirmed appointments cannot be cancelled unilaterally by customer
            raise HTTPException(
                status_code=400,
                detail="Customer cannot unilaterally cancel confirmed APPOINTMENT; cancellation requires Master decision",
            )

        if status not in ("ORDER", "PROPOSAL", "ACCEPTANCE"):
            raise HTTPException(status_code=400, detail=f"Cannot cancel order in status: {status}")

        # Unconfirmed request can be withdrawn directly by customer
        await cur.execute(
            """
            INSERT INTO order_actions (id, order_id, type, initiator, created_at)
            VALUES (%s, %s, 'CANCELLATION', 'CUSTOMER', CURRENT_TIMESTAMP)
            """,
            (uuid4(), order_id),
        )

        await cur.execute(
            """
            UPDATE orders
            SET status = 'VOID',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (order_id,),
        )

    await conn.commit()
    return await get_order_by_id(conn, order_id)
