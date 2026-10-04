"""Conversational Turn-Loop Coordinator for Communication Backend."""

from typing import Any, Callable, Dict, Optional
import psycopg
from ..channels.schemas import (
    BotRole,
    ChannelEventResponse,
    InboundChannelEvent,
)
from .client import PromptEngineClient, RuntimeOutcomeDTO


class TurnLoopCoordinator:
    """Coordinates conversational turn loops between Channel Adapters and Prompt Engine.

    Adheres to the Host Service contract:
    - Prompt Engine owns AI Session, Conversation History, and Execution Context.
    - Communication Backend coordinates context assembly, Prompt Engine invocation,
      operation callbacks, and outbound responses.
    """

    def __init__(
        self,
        prompt_client: PromptEngineClient,
        operation_handler: Optional[Callable[[str, Dict[str, Any], psycopg.AsyncConnection], Any]] = None,
    ):
        self.prompt_client = prompt_client
        self.operation_handler = operation_handler

    async def handle_inbound_event(
        self,
        event: InboundChannelEvent,
        conn: psycopg.AsyncConnection,
        customer_id: Optional[str] = None,
        master_id: Optional[str] = None,
    ) -> ChannelEventResponse:
        # Enforce Bot Context authorization
        if event.bot_role == BotRole.SYSTEM_BOT and not master_id:
            return ChannelEventResponse(
                status="REJECTED",
                error_message="Customer access to System Bot is strictly prohibited",
            )

        conversation_id = f"{event.channel_type.value}:{event.channel_id}:{event.bot_id}"
        runtime_values: Dict[str, Any] = {
            "channel_type": event.channel_type.value,
            "channel_id": event.channel_id,
            "bot_id": event.bot_id,
        }
        if customer_id:
            runtime_values["customer_id"] = str(customer_id)
        if master_id:
            runtime_values["master_id"] = str(master_id)

        try:
            outcome: RuntimeOutcomeDTO = await self.prompt_client.execute_attempt(
                conversation_id=conversation_id,
                message=event.text,
                runtime_values=runtime_values,
            )

            # Handle operation execution callback if Prompt Engine requested CALL_OPERATION
            if outcome.status == "CALL_OPERATION" and outcome.structuredState:
                operation_id = outcome.structuredState.get("operationId")
                args = outcome.structuredState.get("arguments", {})
                if self.operation_handler and operation_id:
                    op_result = await self.operation_handler(operation_id, args, conn)
                    # Submit operation result back to Prompt Engine
                    outcome = await self.prompt_client.submit_interaction(
                        conversation_id=conversation_id,
                        interaction_result={"operationId": operation_id, "result": op_result},
                    )

            if outcome.status == "CONFIRMATION_REQUIRED":
                return ChannelEventResponse(
                    status="CONFIRMATION_REQUIRED",
                    response_text=outcome.text,
                    session_id=outcome.sessionId,
                )

            return ChannelEventResponse(
                status="PROCESSED",
                response_text=outcome.text,
                session_id=outcome.sessionId,
            )

        except Exception as exc:
            return ChannelEventResponse(
                status="ERROR",
                error_message=str(exc),
                response_text="Извините, произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже.",
            )
