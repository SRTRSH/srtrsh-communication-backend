"""Client for Prompt Engine Runtime API."""

from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel


class InteractiveOptionDTO(BaseModel):
    label: str
    result: Dict[str, Any]


class RuntimeOutcomeDTO(BaseModel):
    executionId: str
    status: str
    text: Optional[str] = None
    options: List[InteractiveOptionDTO] = []
    sessionId: Optional[str] = None
    conversationId: Optional[str] = None
    sessionVersion: Optional[int] = None
    structuredState: Optional[Dict[str, Any]] = None
    errorMessage: Optional[str] = None
    telemetry: Optional[Dict[str, Any]] = None


class PromptEngineClient:
    """HTTP client calling Prompt Engine Runtime API as Host Service."""

    def __init__(self, base_url: str = "http://localhost:8000", client: Optional[httpx.AsyncClient] = None):
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def execute_attempt(
        self,
        conversation_id: str,
        message: str,
        runtime_values: Optional[Dict[str, Any]] = None,
        business_references: Optional[Dict[str, Any]] = None,
        case_key: Optional[str] = None,
    ) -> RuntimeOutcomeDTO:
        url = f"{self.base_url}/v1/runtime/execute"
        payload = {
            "conversation_id": conversation_id,
            "message": message,
            "runtime_values": runtime_values or {},
            "business_references": business_references or {},
            "case_key": case_key,
        }

        if self._client is not None:
            resp = await self._client.post(url, json=payload, timeout=30.0)
            resp.raise_for_status()
            return RuntimeOutcomeDTO(**resp.json())

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=30.0)
            resp.raise_for_status()
            return RuntimeOutcomeDTO(**resp.json())

    async def submit_interaction(
        self,
        conversation_id: str,
        interaction_result: Dict[str, Any],
        case_key: Optional[str] = None,
    ) -> RuntimeOutcomeDTO:
        url = f"{self.base_url}/v1/runtime/interaction"
        payload = {
            "conversation_id": conversation_id,
            "interaction_result": interaction_result,
            "case_key": case_key,
        }

        if self._client is not None:
            resp = await self._client.post(url, json=payload, timeout=30.0)
            resp.raise_for_status()
            return RuntimeOutcomeDTO(**resp.json())

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=30.0)
            resp.raise_for_status()
            return RuntimeOutcomeDTO(**resp.json())
