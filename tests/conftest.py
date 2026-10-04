import os
import uuid
from decimal import Decimal
import pytest
import psycopg
from psycopg_pool import AsyncConnectionPool

TEST_DB_URL = os.getenv(
    "SRTRSH_DATABASE_URL",
    "postgres://srtrsh:srtrsh_dev@localhost:5433/srtrsh",
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_pool():
    pool = AsyncConnectionPool(
        conninfo=TEST_DB_URL,
        min_size=1,
        max_size=5,
        open=False,
    )
    await pool.open()
    yield pool
    await pool.close()


@pytest.fixture
async def db_conn(db_pool):
    async with db_pool.connection() as conn:
        yield conn


@pytest.fixture(autouse=True)
def override_app_db(db_conn):
    from srtrsh_communication_backend.db import get_db_connection
    from srtrsh_communication_backend.main import app

    async def _get_conn():
        yield db_conn

    app.dependency_overrides[get_db_connection] = _get_conn
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def clean_test_data(db_conn: psycopg.AsyncConnection):
    """Cleans up test records before and after each test."""
    async def cleanup():
        await db_conn.rollback()
        async with db_conn.cursor() as cur:
            await cur.execute("DELETE FROM order_actions")
            await cur.execute("DELETE FROM order_items")
            await cur.execute("DELETE FROM orders")
            await cur.execute("DELETE FROM services")
            await cur.execute("DELETE FROM workplace_working_periods")
            await cur.execute("DELETE FROM workplaces")
            await cur.execute("DELETE FROM master_customers")
            await cur.execute("DELETE FROM masters")
            await cur.execute("DELETE FROM customers")
            await cur.execute("DELETE FROM business_domain_service_templates")
            await cur.execute("DELETE FROM service_templates")
            await cur.execute("DELETE FROM business_domains")
            await db_conn.commit()

    await cleanup()
    yield
    await cleanup()


@pytest.fixture
async def setup_core_data(db_conn: psycopg.AsyncConnection, clean_test_data):
    master_id = uuid.uuid4()
    customer1_id = uuid.uuid4()
    customer2_id = uuid.uuid4()
    domain_id = uuid.uuid4()
    workplace_id = uuid.uuid4()
    inactive_workplace_id = uuid.uuid4()
    service1_id = uuid.uuid4()
    service2_id = uuid.uuid4()
    suspected_service_id = uuid.uuid4()

    async with db_conn.cursor() as cur:
        await cur.execute("INSERT INTO currencies (code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", ("USD", "US Dollar"))
        await cur.execute("INSERT INTO business_domains (id, name, status) VALUES (%s, %s, %s)", (domain_id, "Beauty & Care", "ACTIVE"))
        
        # Masters
        await cur.execute("INSERT INTO masters (id, telegram_id, warn_cross_workplace_overlaps, status) VALUES (%s, %s, %s, %s)", (master_id, 10001, True, "ACTIVE"))
        
        # Customers
        await cur.execute("INSERT INTO customers (id, telegram_id, name) VALUES (%s, %s, %s)", (customer1_id, 20001, "Alice Customer"))
        await cur.execute("INSERT INTO customers (id, telegram_id, name) VALUES (%s, %s, %s)", (customer2_id, 20002, "Bob Customer"))

        # Workplaces
        await cur.execute(
            """
            INSERT INTO workplaces (id, master_id, business_domain_id, default_currency_code, name, location, atp_duration_minutes, status) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (workplace_id, master_id, domain_id, "USD", "Alice Salon", "Downtown", 30, "ACTIVE")
        )
        await cur.execute(
            """
            INSERT INTO workplaces (id, master_id, business_domain_id, default_currency_code, name, location, atp_duration_minutes, status) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (inactive_workplace_id, master_id, domain_id, "USD", "Closed Salon", "Old Town", 30, "INACTIVE")
        )

        # Services
        await cur.execute(
            """
            INSERT INTO services (id, workplace_id, currency_code, name, duration_atp, price, status, admin_review_state)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (service1_id, workplace_id, "USD", "Haircut", 2, Decimal("40.00"), "ACTIVE", "NORMAL")
        )
        await cur.execute(
            """
            INSERT INTO services (id, workplace_id, currency_code, name, duration_atp, price, status, admin_review_state)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (service2_id, workplace_id, "USD", "Shampoo", 1, Decimal("15.00"), "ACTIVE", "NORMAL")
        )
        await cur.execute(
            """
            INSERT INTO services (id, workplace_id, currency_code, name, duration_atp, price, status, admin_review_state)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (suspected_service_id, workplace_id, "USD", "Suspicious Treatment", 1, Decimal("99.00"), "ACTIVE", "SUSPECTED")
        )

    await db_conn.commit()

    return {
        "master_id": master_id,
        "customer1_id": customer1_id,
        "customer2_id": customer2_id,
        "workplace_id": workplace_id,
        "inactive_workplace_id": inactive_workplace_id,
        "service1_id": service1_id,
        "service2_id": service2_id,
        "suspected_service_id": suspected_service_id,
    }
