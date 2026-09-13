"""`Idempotency-Key` on POST /api/v1/postings: replay, isolation, validation.

Runs against a real throwaway Postgres (testcontainers) under the app role —
the reservation is an `ON CONFLICT DO NOTHING` insert against a composite
primary key, so the whole mechanism lives in the database and an in-memory
fake would prove nothing.
"""

import asyncio

import pytest
from fastapi import status


POSTINGS = "/api/v1/postings"

JD = "Senior Engineer. 5+ years of experience with Kubernetes and Terraform."
OTHER_JD = "Platform Engineer. Experience with Terraform and Postgres."


@pytest.fixture
async def admin_client(auth_client):
    resp = await auth_client.post(
        "/api/v1/auth/token",
        json={
            "username": "operator",
            "password": "correct-password",  # pragma: allowlist secret
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    auth_client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return auth_client


class TestReplay:
    async def test_same_key_twice_replays_one_posting(self, admin_client):
        first = await admin_client.post(
            POSTINGS, content=JD.encode(), headers={"Idempotency-Key": "retry-1"}
        )
        assert first.status_code == status.HTTP_201_CREATED, first.text

        # A different body under the same key still replays the first
        # response: the key, not the payload, is what the client retried.
        second = await admin_client.post(
            POSTINGS, content=OTHER_JD.encode(), headers={"Idempotency-Key": "retry-1"}
        )
        assert second.status_code == status.HTTP_201_CREATED, second.text
        assert second.json() == first.json()

        listing = (await admin_client.get(POSTINGS)).json()["postings"]
        assert len(listing) == 1

    async def test_different_keys_create_two_postings(self, admin_client):
        first = await admin_client.post(
            POSTINGS, content=JD.encode(), headers={"Idempotency-Key": "key-a"}
        )
        second = await admin_client.post(
            POSTINGS, content=OTHER_JD.encode(), headers={"Idempotency-Key": "key-b"}
        )
        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert first.json()["id"] != second.json()["id"]

        listing = (await admin_client.get(POSTINGS)).json()["postings"]
        assert len(listing) == 2

    async def test_no_header_preserves_existing_behavior(self, admin_client):
        """The header is optional; omitting it must not change what the route
        did before — identical text still dedups by content_hash."""
        first = await admin_client.post(POSTINGS, content=JD.encode())
        second = await admin_client.post(POSTINGS, content=JD.encode())
        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["duplicate"] is True

    async def test_concurrent_same_key_creates_one_posting(self, admin_client):
        """The reservation insert IS the lock, so a double-clicked submit
        cannot produce two postings. The loser either replays the winner's
        response or gets a 409 while the winner is still in flight — never a
        second row."""
        responses = await asyncio.gather(
            admin_client.post(
                POSTINGS, content=JD.encode(), headers={"Idempotency-Key": "race-1"}
            ),
            admin_client.post(
                POSTINGS, content=JD.encode(), headers={"Idempotency-Key": "race-1"}
            ),
        )
        codes = sorted(r.status_code for r in responses)
        assert status.HTTP_201_CREATED in codes
        assert codes[1] in (status.HTTP_201_CREATED, status.HTTP_409_CONFLICT)

        listing = (await admin_client.get(POSTINGS)).json()["postings"]
        assert len(listing) == 1


class TestValidation:
    @pytest.mark.parametrize(
        "key",
        [
            "x" * 256,  # over the column's 255 cap
            "bad\x00key",  # non-printable
            "   ",  # empty after stripping
        ],
    )
    async def test_malformed_key_is_rejected(self, admin_client, key):
        """Validated at the trust boundary: a client-supplied string goes
        straight into a primary key, so it is never trusted unchecked."""
        resp = await admin_client.post(
            POSTINGS, content=JD.encode(), headers={"Idempotency-Key": key}
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert (await admin_client.get(POSTINGS)).json()["postings"] == []
