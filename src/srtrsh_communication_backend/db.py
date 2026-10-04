from typing import AsyncGenerator
import psycopg
from psycopg_pool import AsyncConnectionPool
from .config import settings

pool: AsyncConnectionPool | None = None


async def init_pool() -> AsyncConnectionPool:
    global pool
    if pool is None:
        pool = AsyncConnectionPool(
            conninfo=settings.DATABASE_URL,
            min_size=1,
            max_size=10,
            open=False,
        )
        await pool.open()
    return pool


async def close_pool() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


async def get_db_connection() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    global pool
    if pool is None:
        await init_pool()
    async with pool.connection() as conn:
        yield conn
