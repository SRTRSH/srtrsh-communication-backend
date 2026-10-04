# SRTRSH Communication Backend

The canonical, channel-agnostic conversational backend service for SRTRSH.

## Architecture

Communication Backend operates within the canonical closed-loop conversational pipeline:

```text
Human
  ↓
Communication Channel (External Platform: Telegram, WhatsApp, MAX, etc.)
  ↓
Channel Adapter (Thin Protocol Adapter)
  ↓
Communication Backend (Host Service)
  ↓
Prompt Engine (Domain-Agnostic LLM Transformation)
  ↓
operationId
  ↓
Communication Backend (Executes conversational operation against shared database)
  ↓
result
  ↓
Prompt Engine
  ↓
Communication Backend
  ↓
Channel Adapter
  ↓
Human
```

## Key Responsibilities

1. **Host Service of Prompt Engine**:
   - Manages the conversational turn-loop coordination with Prompt Engine (`/v1/runtime/execute`, `/v1/runtime/interaction`).
   - Executes conversational operations requested via `operationId` by Prompt Engine from the Endpoint Catalog.
   - Evaluates cycle outcomes (`NEEDS_USER_INPUT`, `CALL_OPERATION`, `COMPLETED`, `CONFIRMATION_REQUIRED`, `ERROR`).
   - Note: Prompt Engine authoritatively owns AI Session state, conversation history, and execution context.

2. **Conversational Business Operations**:
   - Directly executes conversational operations against the shared business database (`orders`, `order_actions`, `order_items`).
   - `createOrder`: creates new order requests with immutable service snapshots.
   - `customer_proposal`: proposes order time slots.
   - `customer_acceptance`: accepts confirmed proposals.
   - `customer_cancel_order`: customer withdrawals of unconfirmed orders.
   - `list_customer_services`, `get_customer_service_detail`, `get_customer_availability`: catalog and slot calculation.
   - Operates against the same single shared database as Master Backend without proxying or delegating to Master Backend.

3. **Channel Ingress & Identity Resolution**:
   - Accepts normalized inbound events from thin Channel Adapters (`channel_type`, `channel_id`, `text`).
   - Enforces Bot Context authorization (Master-owned Bots serve Customers; System Bot serves Masters).
   - Resolves external Channel Identity (`channel_type`, `channel_id`) to internal SRTRSH identity (`customer_id`, `master_id`).

## Running & Testing

```bash
# Run tests
pytest
```
