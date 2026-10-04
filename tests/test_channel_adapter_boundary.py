import pytest
from httpx import AsyncClient, ASGITransport
import psycopg

from srtrsh_communication_backend.main import app
from srtrsh_communication_backend.channels.schemas import BotRole, ChannelType


@pytest.mark.anyio
async def test_channel_adapter_system_bot_rejects_non_master(
    setup_core_data,
    db_conn: psycopg.AsyncConnection,
):
    d = setup_core_data
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Alice is customer (telegram_id=20001), not a master
        payload = {
            "channel_type": "TELEGRAM",
            "channel_id": "20001",
            "bot_id": "sys_bot_01",
            "bot_role": "SYSTEM_BOT",
            "text": "/manage_schedule",
        }
        res = await client.post("/api/channels/events", json=payload)
        assert res.status_code == 403
        assert "strictly prohibited" in res.json()["detail"]


@pytest.mark.anyio
async def test_channel_adapter_master_bot_accepts_customer(
    setup_core_data,
    db_conn: psycopg.AsyncConnection,
):
    d = setup_core_data
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "channel_type": "TELEGRAM",
            "channel_id": "20001",
            "bot_id": "master_bot_01",
            "bot_role": "MASTER_BOT",
            "text": "Hello, I want to book a haircut",
        }
        res = await client.post("/api/channels/events", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("PROCESSED", "ERROR")
