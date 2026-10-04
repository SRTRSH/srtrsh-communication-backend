from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ChannelType(str, Enum):
    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"
    MAX = "MAX"
    WEB = "WEB"


class BotRole(str, Enum):
    MASTER_BOT = "MASTER_BOT"
    SYSTEM_BOT = "SYSTEM_BOT"


class ChannelIdentity(BaseModel):
    channel_type: ChannelType
    channel_id: str


class InboundChannelEvent(BaseModel):
    channel_type: ChannelType
    channel_id: str
    bot_id: str
    bot_role: BotRole = BotRole.MASTER_BOT
    text: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class OutboundChannelMessage(BaseModel):
    channel_type: ChannelType
    channel_id: str
    text: str
    reply_markup: Optional[Dict[str, Any]] = None


class ChannelEventResponse(BaseModel):
    status: str  # PROCESSED, REJECTED, CONFIRMATION_REQUIRED
    response_text: Optional[str] = None
    session_id: Optional[str] = None
    error_message: Optional[str] = None
