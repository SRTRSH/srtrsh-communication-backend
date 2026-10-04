from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
import psycopg
from httpx import AsyncClient, ASGITransport

from srtrsh_communication_backend.main import app
from srtrsh_communication_backend.catalog.service import add_months


@pytest.mark.anyio
async def test_list_customer_services(setup_core_data, db_conn: psycopg.AsyncConnection):
    d = setup_core_data
    # Add a BLOCKED service
    blocked_id = uuid.uuid4()
    async with db_conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO services (id, workplace_id, currency_code, name, duration_atp, price, status, admin_review_state)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (blocked_id, d["workplace_id"], "USD", "Old Treatment", 1, Decimal("20.00"), "BLOCKED", "NORMAL"),
        )
    await db_conn.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/workplaces/{d['workplace_id']}/services")
        assert res.status_code == 200
        services = res.json()

        # Should only include ACTIVE services with admin_review_state = NORMAL
        # setup_core_data has Haircut (ACTIVE/NORMAL), Shampoo (ACTIVE/NORMAL), Suspicious Treatment (ACTIVE/SUSPECTED)
        # and Old Treatment (BLOCKED/NORMAL)
        assert len(services) == 2
        names = [s["name"] for s in services]
        assert "Haircut" in names
        assert "Shampoo" in names
        assert "Suspicious Treatment" not in names
        assert "Old Treatment" not in names

        haircut = next(s for s in services if s["name"] == "Haircut")
        assert haircut["duration_atp"] == 2
        # Workplace atp_duration_minutes is 30, so 2 * 30 = 60 minutes
        assert haircut["duration_minutes"] == 60
        assert haircut["price"] == "40.00"
        assert haircut["currency_code"] == "USD"
        assert haircut["status"] == "ACTIVE"


@pytest.mark.anyio
async def test_get_customer_service_detail(setup_core_data):
    d = setup_core_data
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Success for ACTIVE/NORMAL
        res = await client.get(f"/api/workplaces/{d['workplace_id']}/services/{d['service1_id']}")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == str(d["service1_id"])
        assert data["name"] == "Haircut"
        assert data["duration_minutes"] == 60

        # 404 for SUSPECTED service
        res_suspected = await client.get(
            f"/api/workplaces/{d['workplace_id']}/services/{d['suspected_service_id']}"
        )
        assert res_suspected.status_code == 404

        # 404 for non-existent service
        res_random = await client.get(
            f"/api/workplaces/{d['workplace_id']}/services/{uuid.uuid4()}"
        )
        assert res_random.status_code == 404


@pytest.mark.anyio
async def test_customer_availability_continuous_free_periods(
    setup_core_data,
    db_conn: psycopg.AsyncConnection,
):
    d = setup_core_data
    # Use dates within the future request window (e.g. tomorrow)
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    # Find the next date matching tomorrow's weekday
    iso_dow = tomorrow.isoweekday()

    async with db_conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO workplace_working_periods (workplace_id, day_of_week, start_time, end_time)
            VALUES (%s, %s, '09:00:00', '13:00:00'), (%s, %s, '14:00:00', '18:00:00')
            """,
            (d["workplace_id"], iso_dow, d["workplace_id"], iso_dow),
        )

        # Confirmed APPOINTMENT at 10:00-11:00
        appt_id = uuid.uuid4()
        appt_start = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
        appt_end = appt_start + timedelta(hours=1)
        await cur.execute(
            """
            INSERT INTO orders (id, customer_id, workplace_id, initiator, status, start_time, end_time)
            VALUES (%s, %s, %s, 'MASTER', 'APPOINTMENT', %s, %s)
            """,
            (appt_id, d["customer1_id"], d["workplace_id"], appt_start, appt_end),
        )

        # Unconfirmed PROPOSAL at 15:00-16:00 (must NOT reduce availability)
        prop_id = uuid.uuid4()
        prop_start = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)
        prop_end = prop_start + timedelta(hours=1)
        await cur.execute(
            """
            INSERT INTO orders (id, customer_id, workplace_id, initiator, status, start_time, end_time)
            VALUES (%s, %s, %s, 'CUSTOMER', 'PROPOSAL', %s, %s)
            """,
            (prop_id, d["customer1_id"], d["workplace_id"], prop_start, prop_end),
        )
    await db_conn.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            f"/api/workplaces/{d['workplace_id']}/availability",
            params={"date_from": tomorrow.isoformat(), "date_to": tomorrow.isoformat()},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["days"]) == 1
        intervals = data["days"][0]["free_intervals"]

        # Free intervals: 09:00-10:00, 11:00-13:00, 14:00-18:00
        assert len(intervals) == 3
        expected_s1 = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
        expected_e1 = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
        expected_s2 = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=11)
        expected_e2 = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=13)
        expected_s3 = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=14)
        expected_e3 = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=18)

        assert intervals[0]["start_time"] == expected_s1.isoformat().replace("+00:00", "Z")
        assert intervals[0]["end_time"] == expected_e1.isoformat().replace("+00:00", "Z")
        assert intervals[1]["start_time"] == expected_s2.isoformat().replace("+00:00", "Z")
        assert intervals[1]["end_time"] == expected_e2.isoformat().replace("+00:00", "Z")
        assert intervals[2]["start_time"] == expected_s3.isoformat().replace("+00:00", "Z")
        assert intervals[2]["end_time"] == expected_e3.isoformat().replace("+00:00", "Z")


@pytest.mark.anyio
async def test_customer_availability_request_period_validation(setup_core_data):
    d = setup_core_data
    today = datetime.now(timezone.utc).date()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Case 1: date_to < date_from -> 400
        res_invalid_range = await client.get(
            f"/api/workplaces/{d['workplace_id']}/availability",
            params={
                "date_from": today.isoformat(),
                "date_to": (today - timedelta(days=1)).isoformat(),
            },
        )
        assert res_invalid_range.status_code == 400

        # Case 2: Exceeding future_request_window_months (default 2 months)
        # e.g. today + 70 days > today + 2 months
        future_limit = add_months(today, 2)
        exceeded_future = future_limit + timedelta(days=5)
        res_exceeded_future = await client.get(
            f"/api/workplaces/{d['workplace_id']}/availability",
            params={
                "date_from": (exceeded_future - timedelta(days=5)).isoformat(),
                "date_to": exceeded_future.isoformat(),
            },
        )
        assert res_exceeded_future.status_code == 400
        assert "future request window" in res_exceeded_future.json()["detail"]

        # Case 3: Exceeding max_request_duration_months (default 1 month)
        # e.g. date_from = today, date_to = today + 40 days
        duration_limit = add_months(today, 1)
        exceeded_duration = duration_limit + timedelta(days=5)
        res_exceeded_duration = await client.get(
            f"/api/workplaces/{d['workplace_id']}/availability",
            params={
                "date_from": today.isoformat(),
                "date_to": exceeded_duration.isoformat(),
            },
        )
        assert res_exceeded_duration.status_code == 400
        assert "maximum allowed request duration" in res_exceeded_duration.json()["detail"]

        # Case 4: Historical / Past request view (canonical rule: no fixed calendar limit)
        past_from = today - timedelta(days=20)
        past_to = today - timedelta(days=10)
        res_past = await client.get(
            f"/api/workplaces/{d['workplace_id']}/availability",
            params={
                "date_from": past_from.isoformat(),
                "date_to": past_to.isoformat(),
            },
        )
        assert res_past.status_code == 200
        past_data = res_past.json()
        assert len(past_data["days"]) == 11
