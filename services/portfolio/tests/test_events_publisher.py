"""`EventPublisher` Protocol conformance and the default no-op adapter."""

import logging

from services.portfolio.events.publisher import (
    EventPublisher,
    LoggingEventPublisher,
    PostingChanged,
)
from services.portfolio.tenancy import TenantId


def _event() -> PostingChanged:
    return PostingChanged(
        posting_id=1, tenant_id=TenantId(1), status="new", content_hash="abc"
    )


async def test_logging_publisher_satisfies_protocol():
    publisher: EventPublisher = LoggingEventPublisher()
    await publisher.publish(_event())


async def test_logging_publisher_logs_the_event(caplog):
    caplog.set_level(logging.INFO)
    await LoggingEventPublisher().publish(_event())
    assert "posting_changed" in caplog.text
    assert "status=new" in caplog.text
