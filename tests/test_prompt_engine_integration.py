import pytest
from srtrsh_communication_backend.channels.schemas import (
    BotRole,
    ChannelType,
    InboundChannelEvent,
)
from srtrsh_communication_backend.prompt_engine.client import (
    PromptEngineClient,
    RuntimeOutcomeDTO,
)
from srtrsh_communication_backend.prompt_engine.coordinator import TurnLoopCoordinator


class MockPromptClient(PromptEngineClient):
    def __init__(self, responses=None):
        super().__init__()
        self.responses = responses or []
        self.calls = []

    async def execute_attempt(self, conversation_id, message, runtime_values=None, business_references=None, case_key=None):
        self.calls.append(("execute", conversation_id, message, runtime_values))
        if self.responses:
            return self.responses.pop(0)
        return RuntimeOutcomeDTO(
            executionId="exec_1",
            status="COMPLETED",
            text="How can I assist you with your booking today?",
            sessionId="sess_123",
            conversationId=conversation_id,
        )

    async def submit_interaction(self, conversation_id, interaction_result, case_key=None):
        self.calls.append(("interaction", conversation_id, interaction_result))
        if self.responses:
            return self.responses.pop(0)
        return RuntimeOutcomeDTO(
            executionId="exec_2",
            status="COMPLETED",
            text="Operation result processed successfully.",
            sessionId="sess_123",
            conversationId=conversation_id,
        )


@pytest.mark.anyio
async def test_turn_loop_coordinator_success(db_conn):
    mock_client = MockPromptClient()
    coordinator = TurnLoopCoordinator(prompt_client=mock_client)

    event = InboundChannelEvent(
        channel_type=ChannelType.TELEGRAM,
        channel_id="20001",
        bot_id="bot_alice",
        bot_role=BotRole.MASTER_BOT,
        text="Hello, what time do you open?",
    )

    resp = await coordinator.handle_inbound_event(
        event=event,
        conn=db_conn,
        customer_id="cust-123",
    )

    assert resp.status == "PROCESSED"
    assert "booking today" in resp.response_text
    assert resp.session_id == "sess_123"
    assert len(mock_client.calls) == 1
    assert mock_client.calls[0][1] == "TELEGRAM:20001:bot_alice"


@pytest.mark.anyio
async def test_turn_loop_coordinator_operation_callback(db_conn):
    # Setup call_operation outcome followed by completed outcome
    call_op_outcome = RuntimeOutcomeDTO(
        executionId="exec_1",
        status="CALL_OPERATION",
        structuredState={
            "operationId": "findAvailableSlots",
            "arguments": {"workplace_id": "wp-1"},
        },
        sessionId="sess_123",
        conversationId="TELEGRAM:20001:bot_alice",
    )
    final_outcome = RuntimeOutcomeDTO(
        executionId="exec_2",
        status="COMPLETED",
        text="Available slots are 10:00, 11:00",
        sessionId="sess_123",
        conversationId="TELEGRAM:20001:bot_alice",
    )
    mock_client = MockPromptClient(responses=[call_op_outcome, final_outcome])

    handled_operations = []

    async def mock_handler(op_id, args, conn):
        handled_operations.append((op_id, args))
        return ["10:00", "11:00"]

    coordinator = TurnLoopCoordinator(
        prompt_client=mock_client,
        operation_handler=mock_handler,
    )

    event = InboundChannelEvent(
        channel_type=ChannelType.TELEGRAM,
        channel_id="20001",
        bot_id="bot_alice",
        bot_role=BotRole.MASTER_BOT,
        text="What slots are free?",
    )

    resp = await coordinator.handle_inbound_event(
        event=event,
        conn=db_conn,
        customer_id="cust-123",
    )

    assert resp.status == "PROCESSED"
    assert resp.response_text == "Available slots are 10:00, 11:00"
    assert len(handled_operations) == 1
    assert handled_operations[0][0] == "findAvailableSlots"
    assert len(mock_client.calls) == 2
