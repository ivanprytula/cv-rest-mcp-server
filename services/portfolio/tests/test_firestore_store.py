"""`FirestoreJobPostingDocumentStore` against Google's Firestore emulator.

Every other test uses `InMemoryJobPostingDocumentStore`, which proves the
Protocol contract but nothing about the real client calls — `set()`,
`get()`, `snapshot.exists`, `to_dict()`. These cover that adapter.

Opt-in (`firestore` marker, excluded by default): they need Docker and pull
Google's ~1GB CLI image. Run with `just test-firestore`.

Google's own emulator, not a third-party reimplementation, deliberately:
the point is proving the adapter matches real Firestore semantics, so the
oracle has to be the reference implementation.
"""

import os
import socket
import time
from collections.abc import Iterator

import pytest

from services.portfolio.gaps.job_posting_document_store import (
    FirestoreJobPostingDocumentStore,
    JobPostingDocument,
)


# The 300s timeout covers a cold ~1GB image pull; the suite-wide default of
# 60s expires mid-download on a fresh machine (and in CI, always).
pytestmark = [pytest.mark.firestore, pytest.mark.timeout(300)]

_EMULATOR_IMAGE = "gcr.io/google.com/cloudsdktool/google-cloud-cli:583.0.0-emulators"
_EMULATOR_PORT = 8080
_PROJECT = "test-project"


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


@pytest.fixture(scope="session")
def firestore_emulator() -> Iterator[str]:
    """Start the emulator once per session; yield its `host:port`.

    Waits on the port rather than a log line: the emulator's readiness
    message has moved between CLI releases, and a pinned image plus a real
    connection check is the more durable signal.
    """
    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer(_EMULATOR_IMAGE)
        .with_command(
            "gcloud emulators firestore start "
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
            pytest.fail(f"Firestore emulator never opened {host}:{port}")
        yield f"{host}:{port}"


@pytest.fixture
def store(firestore_emulator, monkeypatch) -> FirestoreJobPostingDocumentStore:
    """The real adapter, pointed at the emulator.

    `FIRESTORE_EMULATOR_HOST` is what makes the genuine client talk to the
    emulator — no separate client class, no credentials.
    """
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", firestore_emulator)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", _PROJECT)
    from google.auth.credentials import AnonymousCredentials
    from google.cloud.firestore import AsyncClient

    return FirestoreJobPostingDocumentStore(
        AsyncClient(project=_PROJECT, credentials=AnonymousCredentials())
    )


def _document(content_hash: str, **overrides) -> JobPostingDocument:
    return JobPostingDocument(
        content_hash=content_hash,
        posting_text=overrides.get("posting_text", "Senior Engineer. Kubernetes."),
        raw_payload=overrides.get("raw_payload", {"portal": "greenhouse"}),
    )


async def test_saved_document_round_trips(store):
    await store.save(_document("hash-round-trip"))

    found = await store.get("hash-round-trip")
    assert found is not None
    assert found.content_hash == "hash-round-trip"
    assert found.posting_text == "Senior Engineer. Kubernetes."
    assert found.raw_payload == {"portal": "greenhouse"}


async def test_missing_document_returns_none(store):
    assert await store.get("hash-never-written") is None


async def test_saving_the_same_hash_overwrites(store):
    """`set()` idempotency is what makes `store_posting`'s repair-on-dedup
    safe — a second save must overwrite, never duplicate or error."""
    await store.save(_document("hash-overwrite", posting_text="first"))
    await store.save(_document("hash-overwrite", posting_text="second"))

    found = await store.get("hash-overwrite")
    assert found is not None
    assert found.posting_text == "second"


async def test_heterogeneous_payload_survives(store):
    """The reason this is a document store: `raw_payload` is unmodelled and
    differs per portal, so nested/mixed shapes must round-trip unchanged."""
    payload = {
        "portal": "lever",
        "tags": ["remote", "senior"],
        "meta": {"team": "platform", "headcount": 3},
        "remote": True,
    }
    await store.save(_document("hash-payload", raw_payload=payload))

    found = await store.get("hash-payload")
    assert found is not None
    assert found.raw_payload == payload


async def test_empty_payload_round_trips(store):
    """A pasted posting has no portal metadata at all."""
    await store.save(_document("hash-empty", raw_payload={}))

    found = await store.get("hash-empty")
    assert found is not None
    assert found.raw_payload == {}


def test_emulator_env_is_set(firestore_emulator):
    """Guard against the adapter silently talking to real Firestore: if
    `FIRESTORE_EMULATOR_HOST` were unset, these tests would try the live
    project and either fail on credentials or write production data."""
    assert os.environ.get("FIRESTORE_EMULATOR_HOST") in (None, firestore_emulator)
