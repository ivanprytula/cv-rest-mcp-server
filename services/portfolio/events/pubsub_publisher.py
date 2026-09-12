"""GCP Pub/Sub adapter for `EventPublisher` (Phase 3f PR2).

`PublisherClient.publish` is sync and returns a future — wrapped in
`asyncio.to_thread` so a slow publish never blocks the event loop, the same
pattern `GapService.cluster_posting` already uses for the (also blocking)
embedding call.
"""

from __future__ import annotations

import asyncio
import json

from google.cloud.pubsub_v1 import PublisherClient

from services.portfolio.events.publisher import PostingChanged


class PubSubEventPublisher:
    """Publishes `PostingChanged` events as JSON to a Pub/Sub topic."""

    def __init__(self, client: PublisherClient, topic_path: str) -> None:
        self._client = client
        self._topic_path = topic_path

    async def publish(self, event: PostingChanged) -> None:
        payload = json.dumps(
            {
                "posting_id": event.posting_id,
                "tenant_id": int(event.tenant_id),
                "status": event.status,
                "content_hash": event.content_hash,
            }
        ).encode("utf-8")

        def _publish_and_wait() -> None:
            future = self._client.publish(self._topic_path, payload)
            future.result()

        await asyncio.to_thread(_publish_and_wait)


def build_event_publisher_from_settings():
    """`PubSubEventPublisher` if a topic is configured, else the logging fake.

    Empty setting means skip the real client — local dev with no
    `PUBSUB_POSTING_CHANGED_TOPIC` set just logs the event, same
    "empty means skip" pattern as `build_job_posting_document_store_from_settings`.
    """
    from services.portfolio.events.publisher import LoggingEventPublisher
    from services.portfolio.settings import settings

    if not settings.pubsub_posting_changed_topic:
        return LoggingEventPublisher()

    return PubSubEventPublisher(
        PublisherClient(), settings.pubsub_posting_changed_topic
    )
