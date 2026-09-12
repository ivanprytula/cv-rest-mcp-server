"""Posting-change event port — Protocol + the default no-op adapter.

`GapService` depends on the `EventPublisher` Protocol, not a concrete
transport. `PubSubEventPublisher` (Phase 3f PR2) is the real adapter; until
it exists (or when Pub/Sub is unconfigured), `LoggingEventPublisher` is the
default so publishing a `PostingChanged` event is always safe to call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from services.portfolio.tenancy import TenantId


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PostingChanged:
    """A job posting was created or its content changed on re-fetch."""

    posting_id: int
    tenant_id: TenantId
    status: str
    content_hash: str


class EventPublisher(Protocol):
    """Publishes domain events. Fire-and-forget: never blocks the caller."""

    async def publish(self, event: PostingChanged) -> None: ...


class LoggingEventPublisher:
    """Default adapter: logs the event instead of sending it anywhere.

    Keeps `GapService` callable in dev/tests without a Pub/Sub topic
    configured — the same "off by default, on when configured" posture as
    `CVExtractionService`'s optional Anthropic client.
    """

    async def publish(self, event: PostingChanged) -> None:
        logger.info(
            "posting_changed: posting_id=%s tenant_id=%s status=%s",
            event.posting_id,
            event.tenant_id,
            event.status,
        )
