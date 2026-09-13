"""Request correlation ids, taken from Cloud Run's own trace header.

Cloud Run stamps `X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=TRACE_TRUE` on
every inbound request and already records a trace under that id. Reusing it
as the correlation id — rather than exporting spans from an OpenTelemetry
SDK — means log lines join to a trace the platform collected for free, with
no exporter, no sampler and no extra dependency. See ADR-026 for the
trade-off and the trigger to revisit it.

The id lives in a `ContextVar`, so it follows the request across `await`
boundaries without being threaded through every call signature.
`TraceIdFilter` (in the logging config module) reads it and stamps it onto
every record.

Work that outlives its originating request — an outbox row published later
by the relay — carries the id as data and re-binds it with `bind_trace_id`,
which is why that helper exists alongside the middleware.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


_CLOUD_TRACE_HEADER = b"x-cloud-trace-context"

# Empty (not None) so callers can treat "no id" as falsy without a None check.
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


def current_trace_id() -> str:
    """The id for the request in flight, or `""` outside one."""
    return _trace_id.get()


@contextmanager
def bind_trace_id(trace_id: str | None) -> Iterator[str]:
    """Adopt `trace_id` for the duration of the block.

    For work whose id did not arrive on this request's header: the outbox
    relay republishing an event recorded by an earlier request, or a worker
    continuing a trace that started in another service. Falsy input gets a
    fresh id rather than an empty one, so every unit of work is attributable
    to something.
    """
    resolved = trace_id or uuid.uuid4().hex
    token = _trace_id.set(resolved)
    try:
        yield resolved
    finally:
        _trace_id.reset(token)


def _parse_trace_header(raw: bytes) -> str:
    """Pull the trace id out of `TRACE_ID/SPAN_ID;o=1`.

    Only the portion before the first `/` is the trace id; the span id and
    the `o=` sampling flag are Cloud Run's business, not ours.
    """
    return raw.decode("latin-1").split("/", 1)[0].strip()


class TraceContextMiddleware:
    """Binds each HTTP request's Cloud Trace id to the logging context.

    Pure ASGI rather than Starlette's `BaseHTTPMiddleware`: that class runs
    the downstream app in a separate task, and a `ContextVar` set in the
    parent task is not reliably visible to code logging inside the child.

    Requests arriving without the header — local dev, direct container hits,
    tests — get a generated id, so correlation never silently degrades to
    "no id at all" off Cloud Run.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = dict(scope.get("headers") or ()).get(_CLOUD_TRACE_HEADER, b"")
        token = _trace_id.set(_parse_trace_header(raw) or uuid.uuid4().hex)
        try:
            await self.app(scope, receive, send)
        finally:
            # Reset rather than leave set: the same task serves later
            # requests, and a stale id is worse than none.
            _trace_id.reset(token)


__all__ = [
    "TraceContextMiddleware",
    "bind_trace_id",
    "current_trace_id",
]
