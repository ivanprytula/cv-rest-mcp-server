"""Minimal Agent2Agent (A2A) protocol primitives — AgentCard + `SendMessage`.

Hand-rolled to the spec's wire shape rather than adopting the `a2a-sdk`
package: this repo's extractor↔critic round-trip needs exactly one
non-streaming method, well inside "call it twice" territory (see ADR-024).

Verified against the authoritative source (`specification/a2a.proto` and
`docs/specification.md` in `a2aproject/A2A`, main branch) rather than
informal knowledge of the protocol — ADR-024 records two corrections made
during that verification (method name, AgentCard shape) worth reading
before touching this file.

Scope, per ADR-024: `AgentCard` discovery (`/.well-known/agent-card.json`)
and the `SendMessage` JSON-RPC 2.0 method only. No streaming
(`SendStreamingMessage`), no task polling (`GetTask`/`CancelTask`), no
push notifications — none of that is reachable from a one-shot
extract-then-critique flow.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _A2AModel(BaseModel):
    """Base for every A2A wire type: camelCase JSON, snake_case Python.

    A2A's JSON serialization is ProtoJSON (camelCase) — `populate_by_name`
    lets callers construct instances with either the Python or wire name.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Role(StrEnum):
    """`Message.role` — who sent it. Matches the proto's `Role` enum values."""

    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"


class Part(_A2AModel):
    """One piece of a `Message`'s content.

    The spec's `Part` is a single message with a `oneof` content field
    (`text`/`raw`/`url`/`data`) — this repo's extractor↔critic traffic only
    ever needs `text`, so the other three are typed but left unused rather
    than omitted (a `Part` a caller builds by hand should still round-trip
    through a real A2A client if one is ever introduced).
    """

    text: str | None = None
    raw: str | None = None
    url: str | None = None
    data: Any | None = None
    media_type: str | None = None
    filename: str | None = None


class Message(_A2AModel):
    """One unit of communication between client and server."""

    message_id: str
    role: Role
    parts: list[Part]
    context_id: str | None = None
    task_id: str | None = None


class AgentInterface(_A2AModel):
    """One protocol binding this agent is reachable on."""

    url: str
    protocol_binding: Literal["JSONRPC"] = "JSONRPC"
    protocol_version: str = "1.0"


class AgentCapabilities(_A2AModel):
    streaming: bool = False
    push_notifications: bool = False


class AgentSkill(_A2AModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    input_modes: list[str] = Field(default_factory=lambda: ["text/plain"])
    output_modes: list[str] = Field(default_factory=lambda: ["text/plain"])


class AgentCard(_A2AModel):
    """Self-describing manifest served at `/.well-known/agent-card.json`."""

    name: str
    description: str
    supported_interfaces: list[AgentInterface]
    version: str
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    default_input_modes: list[str] = Field(default_factory=lambda: ["text/plain"])
    default_output_modes: list[str] = Field(default_factory=lambda: ["text/plain"])
    skills: list[AgentSkill] = Field(default_factory=list)


class SendMessageRequest(_A2AModel):
    message: Message


class SendMessageResult(_A2AModel):
    """`SendMessageResponse`'s payload — this repo's agents never create a
    `Task` (no async/multi-turn work), so the `message` branch is the only
    one ever populated; `task` stays typed for spec fidelity."""

    message: Message | None = None
    task: dict[str, Any] | None = None


class _JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class _JsonRpcErrorInfo(BaseModel):
    type_: str = Field(
        default="type.googleapis.com/google.rpc.ErrorInfo", alias="@type"
    )
    reason: str
    domain: str = "a2a-protocol.org"
    metadata: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class _JsonRpcError(BaseModel):
    code: int
    message: str
    data: list[_JsonRpcErrorInfo] = Field(default_factory=list)


class _JsonRpcResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None
    result: dict[str, Any] | None = None
    error: _JsonRpcError | None = None


SendMessageHandler = Callable[[Message], Awaitable[Message]]


def a2a_router(*, agent_card: AgentCard, handler: SendMessageHandler) -> APIRouter:
    """Build the two routes an A2A agent needs: discovery + `SendMessage`.

    `handler` receives the incoming `Message` and returns the agent's reply
    `Message` — the router owns nothing about what the agent does, only the
    envelope around it.
    """
    router = APIRouter()

    @router.get("/.well-known/agent-card.json", response_model=AgentCard)
    async def get_agent_card() -> AgentCard:
        return agent_card

    @router.post("/a2a")
    async def rpc(body: dict[str, Any]) -> _JsonRpcResponse:
        try:
            request = _JsonRpcRequest.model_validate(body)
        except Exception:
            return _JsonRpcResponse(
                id=body.get("id") if isinstance(body, dict) else None,
                error=_JsonRpcError(
                    code=-32600,
                    message="Invalid Request",
                    data=[_JsonRpcErrorInfo(reason="INVALID_REQUEST")],
                ),
            )

        if request.method != "SendMessage":
            return _JsonRpcResponse(
                id=request.id,
                error=_JsonRpcError(
                    code=-32601,
                    message="Method not found",
                    data=[
                        _JsonRpcErrorInfo(
                            reason="METHOD_NOT_FOUND",
                            metadata={"method": request.method},
                        )
                    ],
                ),
            )

        try:
            send_request = SendMessageRequest.model_validate(request.params)
        except Exception:
            return _JsonRpcResponse(
                id=request.id,
                error=_JsonRpcError(
                    code=-32602,
                    message="Invalid params",
                    data=[_JsonRpcErrorInfo(reason="INVALID_PARAMS")],
                ),
            )

        reply = await handler(send_request.message)
        result = SendMessageResult(message=reply)
        return _JsonRpcResponse(
            id=request.id,
            result=result.model_dump(by_alias=True, exclude_none=True),
        )

    return router
