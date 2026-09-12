"""A2A envelope round-trip — AgentCard discovery + `SendMessage` JSON-RPC.

Builds a router from a trivial echo handler and asserts the wire shapes
match the spec verified in ADR-024 (method name, camelCase fields, error
envelope) rather than the informal shapes an earlier draft of that ADR
assumed before checking the source.
"""

import httpx
import pytest
from fastapi import FastAPI

from services.portfolio.cv_review.a2a import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Role,
    a2a_router,
)


def _agent_card() -> AgentCard:
    return AgentCard(
        name="Echo Agent",
        description="Echoes back whatever it receives.",
        supported_interfaces=[
            AgentInterface(url="https://example.com/a2a", protocol_version="1.0")
        ],
        version="0.1.0",
        capabilities=AgentCapabilities(),
        skills=[
            AgentSkill(
                id="echo",
                name="Echo",
                description="Repeats the input text back.",
                tags=["test"],
            )
        ],
    )


async def _echo_handler(message: Message) -> Message:
    return Message(
        message_id="reply-1",
        role=Role.AGENT,
        parts=message.parts,
        context_id=message.context_id,
        task_id=message.task_id,
    )


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(a2a_router(agent_card=_agent_card(), handler=_echo_handler))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_agent_card_is_served_at_the_well_known_path(client):
    response = await client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Echo Agent"
    assert body["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
    assert body["defaultInputModes"] == ["text/plain"]


async def test_send_message_round_trips(client):
    response = await client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "msg-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "hello"}],
                }
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert body["error"] is None
    assert body["result"]["message"]["messageId"] == "reply-1"
    assert body["result"]["message"]["role"] == "ROLE_AGENT"
    assert body["result"]["message"]["parts"] == [{"text": "hello"}]


async def test_unknown_method_returns_json_rpc_error(client):
    response = await client.post(
        "/a2a", json={"jsonrpc": "2.0", "id": 2, "method": "GetTask", "params": {}}
    )
    body = response.json()
    assert body["result"] is None
    assert body["error"]["code"] == -32601
    assert body["error"]["data"][0]["reason"] == "METHOD_NOT_FOUND"


async def test_malformed_request_returns_invalid_request_error(client):
    response = await client.post("/a2a", json={"not": "a jsonrpc envelope"})
    body = response.json()
    assert body["error"]["code"] == -32600
    assert body["error"]["data"][0]["reason"] == "INVALID_REQUEST"
