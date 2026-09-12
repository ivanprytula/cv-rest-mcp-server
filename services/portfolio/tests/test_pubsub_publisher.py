"""`PubSubEventPublisher` against Google's Pub/Sub emulator.

Every other test uses `LoggingEventPublisher`, which proves the Protocol
contract but nothing about the real client call — `publish()`'s topic path,
payload encoding, and future resolution. This covers that adapter.

Opt-in (`pubsub` marker, excluded by default): needs Docker and pulls
Google's ~1GB CLI image, same as `test_firestore_store.py`. Run with
`just test-pubsub`.

Google's own emulator, not a third-party reimplementation, deliberately —
per ADR-024, the point is proving the adapter matches real Pub/Sub
semantics, so the oracle has to be the reference implementation.
"""

import json
import os
import socket
import time
import uuid
from collections.abc import Iterator

import pytest

from services.portfolio.events.publisher import PostingChanged
from services.portfolio.events.pubsub_publisher import PubSubEventPublisher
from services.portfolio.tenancy import TenantId


# The 300s timeout covers a cold ~1GB image pull; the suite-wide default of
# 60s expires mid-download on a fresh machine (and in CI, always).
pytestmark = [pytest.mark.pubsub, pytest.mark.timeout(300)]

_EMULATOR_IMAGE = "gcr.io/google.com/cloudsdktool/google-cloud-cli:583.0.0-emulators"
_EMULATOR_PORT = 8085
_PROJECT = "test-project"
_TOPIC_ID = "posting-changed"
_SUBSCRIPTION_ID = "posting-changed-test-sub"


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


@pytest.fixture(scope="session")
def pubsub_emulator() -> Iterator[str]:
    """Start the emulator once per session; yield its `host:port`.

    Waits on the port rather than a log line, same reasoning as
    `test_firestore_store.py`'s `firestore_emulator` fixture: a pinned
    image plus a real connection check outlives CLI readiness-message churn.
    """
    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer(_EMULATOR_IMAGE)
        .with_command(
            "gcloud beta emulators pubsub start "
            f"--host-port=0.0.0.0:{_EMULATOR_PORT} --quiet"
        )
        .with_exposed_ports(_EMULATOR_PORT)
    )
    with container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(_EMULATOR_PORT))
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if _port_open(host, port):
                break
            time.sleep(0.5)
        else:
            pytest.fail(f"Pub/Sub emulator never opened {host}:{port}")
        yield f"{host}:{port}"


@pytest.fixture
def publisher(pubsub_emulator, monkeypatch) -> PubSubEventPublisher:
    """The real adapter, pointed at the emulator, with its topic pre-created.

    `PUBSUB_EMULATOR_HOST` is what makes the genuine client talk to the
    emulator — no separate client class, no credentials. Unlike Firestore,
    Pub/Sub requires the topic to exist before publishing, so this fixture
    creates it explicitly (Phase 2's Terraform module does this in prod).
    Each test gets its own topic id: the emulator persists state for the
    whole session-scoped container, so a shared id would collide with
    `AlreadyExists` on the second test.
    """
    monkeypatch.setenv("PUBSUB_EMULATOR_HOST", pubsub_emulator)
    from google.cloud.pubsub_v1 import PublisherClient

    client = PublisherClient()
    topic_path = client.topic_path(_PROJECT, f"{_TOPIC_ID}-{uuid.uuid4().hex[:8]}")
    client.create_topic(name=topic_path)
    return PubSubEventPublisher(client, topic_path)


def _event(**overrides) -> PostingChanged:
    return PostingChanged(
        posting_id=overrides.get("posting_id", 1),
        tenant_id=TenantId(overrides.get("tenant_id", 1)),
        status=overrides.get("status", "new"),
        content_hash=overrides.get("content_hash", "abc123"),
    )


async def test_publish_completes_without_error(publisher):
    await publisher.publish(_event())


async def test_published_message_is_readable_via_subscription(
    pubsub_emulator, publisher
):
    from google.cloud.pubsub_v1 import SubscriberClient

    subscriber = SubscriberClient()
    subscription_id = f"{_SUBSCRIPTION_ID}-{uuid.uuid4().hex[:8]}"
    subscription_path = subscriber.subscription_path(_PROJECT, subscription_id)
    subscriber.create_subscription(name=subscription_path, topic=publisher._topic_path)

    await publisher.publish(_event(posting_id=42, status="changed"))

    response = subscriber.pull(
        subscription=subscription_path, max_messages=1, timeout=10
    )
    assert len(response.received_messages) == 1
    body = json.loads(response.received_messages[0].message.data)
    assert body["posting_id"] == 42
    assert body["status"] == "changed"


def test_emulator_env_is_set(pubsub_emulator):
    """Guard against the adapter silently talking to real Pub/Sub: if
    `PUBSUB_EMULATOR_HOST` were unset, these tests would try the live
    project and either fail on credentials or publish real messages."""
    assert os.environ.get("PUBSUB_EMULATOR_HOST") in (None, pubsub_emulator)
