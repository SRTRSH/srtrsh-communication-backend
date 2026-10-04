import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
import psycopg
from httpx import AsyncClient, ASGITransport

from srtrsh_communication_backend.main import app


@pytest.mark.anyio
async def test_create_order_success_and_immutable_snapshots(
    setup_core_data,
    db_conn: psycopg.AsyncConnection,
):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = start_time + timedelta(hours=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "customer_id": str(d["customer1_id"]),
            "workplace_id": str(d["workplace_id"]),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "items": [
                {"service_id": str(d["service1_id"]), "quantity": 1},
                {"service_id": str(d["service2_id"]), "quantity": 2},
            ],
        }
        res = await client.post("/api/orders", json=payload)
        assert res.status_code == 201
        data = res.json()

        assert data["status"] == "ORDER"
        assert data["initiator"] == "CUSTOMER"
        assert data["customer_id"] == str(d["customer1_id"])
        assert data["workplace_id"] == str(d["workplace_id"])
        assert len(data["items"]) == 2
        assert len(data["actions"]) == 0

        item1 = next(it for it in data["items"] if it["service_id"] == str(d["service1_id"]))
        assert item1["name"] == "Haircut"
        assert item1["price"] == "40.00"
        assert item1["currency_code"] == "USD"
        assert item1["duration_atp"] == 2
        assert item1["quantity"] == 1

        item2 = next(it for it in data["items"] if it["service_id"] == str(d["service2_id"]))
        assert item2["name"] == "Shampoo"
        assert item2["price"] == "15.00"
        assert item2["currency_code"] == "USD"
        assert item2["duration_atp"] == 1
        assert item2["quantity"] == 2

        # Verify historical snapshot immutability: update service price in DB
        async with db_conn.cursor() as cur:
            await cur.execute(
                "UPDATE services SET price = 999.00, name = 'Changed Name' WHERE id = %s",
                (d["service1_id"],),
            )
        await db_conn.commit()

        # Re-fetch order: snapshot must remain unchanged
        get_res = await client.get(f"/api/orders/{data['id']}")
        assert get_res.status_code == 200
        re_fetched = get_res.json()
        item1_refetched = next(it for it in re_fetched["items"] if it["service_id"] == str(d["service1_id"]))
        assert item1_refetched["name"] == "Haircut"
        assert item1_refetched["price"] == "40.00"


@pytest.mark.anyio
async def test_create_order_validations(setup_core_data):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = start_time + timedelta(hours=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Non-existent customer
        res1 = await client.post(
            "/api/orders",
            json={
                "customer_id": str(uuid.uuid4()),
                "workplace_id": str(d["workplace_id"]),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        assert res1.status_code == 404

        # 2. Non-existent workplace
        res2 = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(uuid.uuid4()),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        assert res2.status_code == 404

        # 3. Inactive workplace
        res3 = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["inactive_workplace_id"]),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        assert res3.status_code == 400
        assert "Workplace is not active" in res3.json()["detail"]

        # 4. Service in SUSPECTED review state
        res4 = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["workplace_id"]),
                "items": [{"service_id": str(d["suspected_service_id"]), "quantity": 1}],
            },
        )
        assert res4.status_code == 400
        assert "SUSPECTED review" in res4.json()["detail"]

        # 5. Invalid time interval: end_time <= start_time
        res5 = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["workplace_id"]),
                "start_time": end_time.isoformat(),
                "end_time": start_time.isoformat(),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        assert res5.status_code == 400
        assert "end_time must be greater than start_time" in res5.json()["detail"]


@pytest.mark.anyio
async def test_customer_proposal_and_history(setup_core_data):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = start_time + timedelta(hours=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create initial order
        res_create = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["workplace_id"]),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        order_id = res_create.json()["id"]

        # 1. Customer Proposal 1
        prop1_start = now + timedelta(days=2, hours=10)
        prop1_end = prop1_start + timedelta(hours=1)
        res_prop1 = await client.post(
            f"/api/orders/{order_id}/proposals",
            json={
                "customer_id": str(d["customer1_id"]),
                "start_time": prop1_start.isoformat(),
                "end_time": prop1_end.isoformat(),
            },
        )
        assert res_prop1.status_code == 200
        data1 = res_prop1.json()
        assert data1["status"] == "PROPOSAL"
        assert len(data1["actions"]) == 1
        assert data1["actions"][0]["type"] == "PROPOSAL"
        assert data1["actions"][0]["initiator"] == "CUSTOMER"

        # 2. Customer Proposal 2 (repeated proposal permitted)
        prop2_start = now + timedelta(days=3, hours=14)
        prop2_end = prop2_start + timedelta(hours=1)
        res_prop2 = await client.post(
            f"/api/orders/{order_id}/proposals",
            json={
                "customer_id": str(d["customer1_id"]),
                "start_time": prop2_start.isoformat(),
                "end_time": prop2_end.isoformat(),
            },
        )
        assert res_prop2.status_code == 200
        data2 = res_prop2.json()
        assert data2["status"] == "PROPOSAL"
        assert len(data2["actions"]) == 2
        assert data2["actions"][1]["type"] == "PROPOSAL"
        assert data2["actions"][1]["initiator"] == "CUSTOMER"


@pytest.mark.anyio
async def test_customer_acceptance(setup_core_data, db_conn: psycopg.AsyncConnection):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = start_time + timedelta(hours=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create initial order
        res_create = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["workplace_id"]),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        order_id = res_create.json()["id"]

        # Simulate Master Proposal in DB
        async with db_conn.cursor() as cur:
            master_prop_start = now + timedelta(days=2, hours=11)
            master_prop_end = master_prop_start + timedelta(hours=1)
            await cur.execute(
                """
                INSERT INTO order_actions (id, order_id, type, initiator, start_time, end_time, created_at)
                VALUES (%s, %s, 'PROPOSAL', 'MASTER', %s, %s, CURRENT_TIMESTAMP)
                """,
                (uuid.uuid4(), order_id, master_prop_start, master_prop_end),
            )
            await cur.execute(
                "UPDATE orders SET status = 'PROPOSAL', start_time = %s, end_time = %s WHERE id = %s",
                (master_prop_start, master_prop_end, order_id),
            )
        await db_conn.commit()

        # Customer Acceptance
        res_accept = await client.post(
            f"/api/orders/{order_id}/accept",
            json={
                "customer_id": str(d["customer1_id"]),
            },
        )
        assert res_accept.status_code == 200
        data_accept = res_accept.json()
        # Status becomes ACCEPTANCE, NOT APPOINTMENT (Master acceptance confirms appointment)
        assert data_accept["status"] == "ACCEPTANCE"
        assert len(data_accept["actions"]) == 2
        assert data_accept["actions"][1]["type"] == "ACCEPTANCE"
        assert data_accept["actions"][1]["initiator"] == "CUSTOMER"


@pytest.mark.anyio
async def test_customer_cancellation_unconfirmed(setup_core_data):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = start_time + timedelta(hours=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create initial order (ORDER)
        res_create = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["workplace_id"]),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        order_id = res_create.json()["id"]

        # Cancel unconfirmed order
        res_cancel = await client.post(
            f"/api/orders/{order_id}/cancel",
            json={"customer_id": str(d["customer1_id"])},
        )
        assert res_cancel.status_code == 200
        data_cancel = res_cancel.json()
        assert data_cancel["status"] == "VOID"
        assert len(data_cancel["actions"]) == 1
        assert data_cancel["actions"][0]["type"] == "CANCELLATION"
        assert data_cancel["actions"][0]["initiator"] == "CUSTOMER"


@pytest.mark.anyio
async def test_terminal_void_protection(setup_core_data):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = start_time + timedelta(hours=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res_create = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["workplace_id"]),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        order_id = res_create.json()["id"]

        # Cancel order -> VOID
        await client.post(
            f"/api/orders/{order_id}/cancel",
            json={"customer_id": str(d["customer1_id"])},
        )

        # 1. Proposal on VOID -> rejected
        res_prop = await client.post(
            f"/api/orders/{order_id}/proposals",
            json={
                "customer_id": str(d["customer1_id"]),
                "start_time": (now + timedelta(days=2)).isoformat(),
                "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
            },
        )
        assert res_prop.status_code == 400
        assert "cancelled (VOID)" in res_prop.json()["detail"]

        # 2. Accept on VOID -> rejected
        res_acc = await client.post(
            f"/api/orders/{order_id}/accept",
            json={"customer_id": str(d["customer1_id"])},
        )
        assert res_acc.status_code == 400
        assert "cancelled (VOID)" in res_acc.json()["detail"]

        # 3. Cancel on VOID -> rejected
        res_canc = await client.post(
            f"/api/orders/{order_id}/cancel",
            json={"customer_id": str(d["customer1_id"])},
        )
        assert res_canc.status_code == 400
        assert "already cancelled" in res_canc.json()["detail"]


@pytest.mark.anyio
async def test_confirmed_appointment_and_expiry_rejections(
    setup_core_data,
    db_conn: psycopg.AsyncConnection,
):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    future_start = now + timedelta(days=2)
    future_end = future_start + timedelta(hours=1)
    past_start = now - timedelta(days=1, hours=2)
    past_end = now - timedelta(days=1, hours=1)

    confirmed_order_id = uuid.uuid4()
    expired_order_id = uuid.uuid4()

    async with db_conn.cursor() as cur:
        # Confirmed APPOINTMENT in future
        await cur.execute(
            """
            INSERT INTO orders (id, customer_id, workplace_id, initiator, status, start_time, end_time, created_at, updated_at)
            VALUES (%s, %s, %s, 'MASTER', 'APPOINTMENT', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (confirmed_order_id, d["customer1_id"], d["workplace_id"], future_start, future_end),
        )
        # Expired APPOINTMENT in past
        await cur.execute(
            """
            INSERT INTO orders (id, customer_id, workplace_id, initiator, status, start_time, end_time, created_at, updated_at)
            VALUES (%s, %s, %s, 'MASTER', 'APPOINTMENT', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (expired_order_id, d["customer1_id"], d["workplace_id"], past_start, past_end),
        )
    await db_conn.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Customer cancellation of confirmed APPOINTMENT -> REJECTED
        res_canc_conf = await client.post(
            f"/api/orders/{confirmed_order_id}/cancel",
            json={"customer_id": str(d["customer1_id"])},
        )
        assert res_canc_conf.status_code == 400
        assert "Customer cannot unilaterally cancel confirmed APPOINTMENT" in res_canc_conf.json()["detail"]

        # 2. Customer proposal on confirmed APPOINTMENT -> REJECTED
        res_prop_conf = await client.post(
            f"/api/orders/{confirmed_order_id}/proposals",
            json={
                "customer_id": str(d["customer1_id"]),
                "start_time": (now + timedelta(days=3)).isoformat(),
                "end_time": (now + timedelta(days=3, hours=1)).isoformat(),
            },
        )
        assert res_prop_conf.status_code == 400

        # 3. Mutations on expired APPOINTMENT -> REJECTED (immutable)
        res_canc_exp = await client.post(
            f"/api/orders/{expired_order_id}/cancel",
            json={"customer_id": str(d["customer1_id"])},
        )
        assert res_canc_exp.status_code == 400
        assert "expired and is immutable" in res_canc_exp.json()["detail"]

        res_prop_exp = await client.post(
            f"/api/orders/{expired_order_id}/proposals",
            json={
                "customer_id": str(d["customer1_id"]),
                "start_time": (now + timedelta(days=1)).isoformat(),
                "end_time": (now + timedelta(days=1, hours=1)).isoformat(),
            },
        )
        assert res_prop_exp.status_code == 400
        assert "expired and is immutable" in res_prop_exp.json()["detail"]


@pytest.mark.anyio
async def test_authorization_and_customer_orders_listing(setup_core_data):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = start_time + timedelta(hours=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create order for Customer 1
        res1 = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["workplace_id"]),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        order_c1_id = res1.json()["id"]

        # Create order for Customer 2
        res2 = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer2_id"]),
                "workplace_id": str(d["workplace_id"]),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "items": [{"service_id": str(d["service2_id"]), "quantity": 1}],
            },
        )
        order_c2_id = res2.json()["id"]

        # 1. Customer 2 tries to access / mutate Customer 1's order -> 403 Forbidden
        res_get_unauth = await client.get(
            f"/api/orders/{order_c1_id}",
            params={"customer_id": str(d["customer2_id"])},
        )
        assert res_get_unauth.status_code == 403

        res_prop_unauth = await client.post(
            f"/api/orders/{order_c1_id}/proposals",
            json={
                "customer_id": str(d["customer2_id"]),
                "start_time": (now + timedelta(days=2)).isoformat(),
                "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
            },
        )
        assert res_prop_unauth.status_code == 403

        res_cancel_unauth = await client.post(
            f"/api/orders/{order_c1_id}/cancel",
            json={"customer_id": str(d["customer2_id"])},
        )
        assert res_cancel_unauth.status_code == 403

        # 2. List orders per customer
        list_c1 = await client.get(f"/api/orders/customer/{d['customer1_id']}")
        assert list_c1.status_code == 200
        orders_c1 = list_c1.json()
        assert len(orders_c1) == 1
        assert orders_c1[0]["id"] == order_c1_id

        list_c2 = await client.get(f"/api/orders/customer/{d['customer2_id']}")
        assert list_c2.status_code == 200
        orders_c2 = list_c2.json()
        assert len(orders_c2) == 1
        assert orders_c2[0]["id"] == order_c2_id


@pytest.mark.anyio
async def test_concurrency_protection(setup_core_data):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = start_time + timedelta(hours=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["workplace_id"]),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        order_id = res.json()["id"]

        # Run conflicting concurrent mutations: Proposal and Cancel
        p1 = client.post(
            f"/api/orders/{order_id}/proposals",
            json={
                "customer_id": str(d["customer1_id"]),
                "start_time": (now + timedelta(days=2)).isoformat(),
                "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
            },
        )
        p2 = client.post(
            f"/api/orders/{order_id}/cancel",
            json={"customer_id": str(d["customer1_id"])},
        )

        res_p1, res_p2 = await asyncio.gather(p1, p2, return_exceptions=True)
        # One of them must succeed; if cancel finishes first, proposal will fail with 400.
        # If proposal finishes first, both can succeed sequentially (proposal then cancel).
        # Neither should corrupt the DB state or deadlock.
        assert res_p1.status_code in (200, 400)
        assert res_p2.status_code in (200, 400)


@pytest.mark.anyio
async def test_master_customers_association_and_customer_appointments(
    setup_core_data,
    db_conn: psycopg.AsyncConnection,
):
    d = setup_core_data
    now = datetime.now(timezone.utc)
    start_time_1 = now + timedelta(days=2)
    end_time_1 = start_time_1 + timedelta(hours=1)
    start_time_2 = now + timedelta(days=5)
    end_time_2 = start_time_2 + timedelta(hours=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Check master_customers is initially empty for master and customer1
        async with db_conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM master_customers WHERE master_id = %s AND customer_id = %s",
                (d["master_id"], d["customer1_id"]),
            )
            count = (await cur.fetchone())[0]
            assert count == 0

        # Create Order (status=ORDER)
        res_order = await client.post(
            "/api/orders",
            json={
                "customer_id": str(d["customer1_id"]),
                "workplace_id": str(d["workplace_id"]),
                "start_time": start_time_1.isoformat(),
                "end_time": end_time_1.isoformat(),
                "items": [{"service_id": str(d["service1_id"]), "quantity": 1}],
            },
        )
        assert res_order.status_code == 201
        order_id = res_order.json()["id"]

        # Check master_customers now has an entry
        async with db_conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM master_customers WHERE master_id = %s AND customer_id = %s",
                (d["master_id"], d["customer1_id"]),
            )
            count = (await cur.fetchone())[0]
            assert count == 1

        # Customer acceptance also runs idempotently
        res_accept = await client.post(
            f"/api/orders/{order_id}/accept",
            json={"customer_id": str(d["customer1_id"])},
        )
        assert res_accept.status_code == 200

        # Verify master_customers still has exactly 1 entry (idempotent)
        async with db_conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM master_customers WHERE master_id = %s AND customer_id = %s",
                (d["master_id"], d["customer1_id"]),
            )
            count = (await cur.fetchone())[0]
            assert count == 1

        # Create a confirmed APPOINTMENT order directly in DB for date filtering tests
        appt_order_id = uuid.uuid4()
        async with db_conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO orders (id, customer_id, workplace_id, initiator, status, start_time, end_time, created_at, updated_at)
                VALUES (%s, %s, %s, 'MASTER', 'APPOINTMENT', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (appt_order_id, d["customer1_id"], d["workplace_id"], start_time_2, end_time_2),
            )
        await db_conn.commit()

        # 1. Filter orders by status
        res_filter_appt = await client.get(
            f"/api/orders/customer/{d['customer1_id']}",
            params={"status": "APPOINTMENT"},
        )
        assert res_filter_appt.status_code == 200
        appts = res_filter_appt.json()
        assert len(appts) == 1
        assert appts[0]["id"] == str(appt_order_id)
        assert appts[0]["status"] == "APPOINTMENT"

        res_filter_accept = await client.get(
            f"/api/orders/customer/{d['customer1_id']}",
            params={"status": "ACCEPTANCE"},
        )
        assert res_filter_accept.status_code == 200
        accepts = res_filter_accept.json()
        assert len(accepts) == 1
        assert accepts[0]["id"] == order_id

        # 2. Filter orders by date range
        date_1_str = start_time_1.date().isoformat()
        res_date_1 = await client.get(
            f"/api/orders/customer/{d['customer1_id']}",
            params={"date_from": date_1_str, "date_to": date_1_str},
        )
        assert res_date_1.status_code == 200
        orders_d1 = res_date_1.json()
        assert len(orders_d1) == 1
        assert orders_d1[0]["id"] == order_id

        # 3. Customer appointments endpoint
        res_appts_all = await client.get(f"/api/orders/customer/{d['customer1_id']}/appointments")
        assert res_appts_all.status_code == 200
        assert len(res_appts_all.json()) == 1
        assert res_appts_all.json()[0]["id"] == str(appt_order_id)

        # Appointments endpoint with date filtering
        date_2_str = start_time_2.date().isoformat()
        res_appts_d2 = await client.get(
            f"/api/orders/customer/{d['customer1_id']}/appointments",
            params={"date_from": date_2_str, "date_to": date_2_str},
        )
        assert res_appts_d2.status_code == 200
        assert len(res_appts_d2.json()) == 1

        # Out-of-range date filter returns empty list
        yesterday_str = (now - timedelta(days=1)).date().isoformat()
        res_appts_empty = await client.get(
            f"/api/orders/customer/{d['customer1_id']}/appointments",
            params={"date_from": yesterday_str, "date_to": yesterday_str},
        )
        assert res_appts_empty.status_code == 200
        assert len(res_appts_empty.json()) == 0

