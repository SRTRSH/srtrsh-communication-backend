from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
import psycopg
from psycopg.rows import dict_row

from ..db import get_db_connection
from ..config import settings
from ..prompt_engine.client import PromptEngineClient
from ..prompt_engine.coordinator import TurnLoopCoordinator
from .schemas import (
    BotRole,
    ChannelEventResponse,
    ChannelType,
    InboundChannelEvent,
)

router = APIRouter(prefix="/api/channels", tags=["Channel Ingress"])


async def resolve_channel_identity(
    conn: psycopg.AsyncConnection,
    channel_type: ChannelType,
    channel_id: str,
) -> tuple[Optional[UUID], Optional[UUID]]:
    """Resolves channel identity (channel_type, channel_id) to internal (customer_id, master_id)."""
    customer_id: Optional[UUID] = None
    master_id: Optional[UUID] = None

    async with conn.cursor(row_factory=dict_row) as cur:
        if channel_type == ChannelType.TELEGRAM:
            try:
                tg_id = int(channel_id)
            except ValueError:
                return None, None

            # Look up customer
            await cur.execute("SELECT id FROM customers WHERE telegram_id = %s", (tg_id,))
            crow = await cur.fetchone()
            if crow:
                customer_id = crow["id"]

            # Look up master
            await cur.execute("SELECT id FROM masters WHERE telegram_id = %s", (tg_id,))
            mrow = await cur.fetchone()
            if mrow:
                master_id = mrow["id"]

    return customer_id, master_id


@router.post(
    "/events",
    response_model=ChannelEventResponse,
    status_code=status.HTTP_200_OK,
)
async def handle_channel_event_endpoint(
    event: InboundChannelEvent,
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    """Channel-agnostic ingress endpoint for thin Channel Adapters.

    Channel Adapters normalize platform-specific webhooks/messages and POST
    to this endpoint. Communication Backend enforces Bot Context authorization,
    resolves identity, and executes the conversational turn loop with Prompt Engine.
    """
    customer_id, master_id = await resolve_channel_identity(
        conn, event.channel_type, event.channel_id
    )

    # Invariant: System Bot context strictly prohibits Customer access
    if event.bot_role == BotRole.SYSTEM_BOT:
        if not master_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customer access to System Bot is strictly prohibited",
            )

    client = PromptEngineClient(base_url=settings.PROMPT_ENGINE_URL)
    coordinator = TurnLoopCoordinator(prompt_client=client)

    return await coordinator.handle_inbound_event(
        event=event,
        conn=conn,
        customer_id=str(customer_id) if customer_id else None,
        master_id=str(master_id) if master_id else None,
    )
