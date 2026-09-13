"""Transactional outbox: atomicity with the posting write, and the relay.

Runs against a real throwaway Postgres (testcontainers) under the non-superuser
app role, like the other persistence tests — the whole point here is
transaction and locking behavior (`FOR UPDATE SKIP LOCKED`, a rolled-back
insert), none of which an in-memory fake would exercise honestly.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from services.portfolio.events.outbox_row import EventOutboxRow
from services.portfolio.gaps.gap_repository import SqlAlchemyGapRepository
from services.portfolio.gaps.job_posting_row import JobPostingRow
from services.portfolio.main import app
from services.portfolio.tenancy import TenantId


@pytest.fixture
def gap_service(user_service):
    return app.state.gap_service


@pytest.fixture
def gap_repo(session_factory):
    return SqlAlchemyGapRepository(session_factory)


async def _pending_events(session_factory) -> list[EventOutboxRow]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(EventOutboxRow)
                .where(EventOutboxRow.published_at.is_(None))
                .order_by(EventOutboxRow.id)
            )
        ).scalars()
        return list(rows)


async def _all_events(session_factory) -> list[EventOutboxRow]:
    async with session_factory() as session:
        rows = (
            await session.execute(select(EventOutboxRow).order_by(EventOutboxRow.id))
        ).scalars()
        return list(rows)


class TestAtomicity:
    async def test_store_posting_writes_one_pending_event(
        self, gap_service, session_factory, operator_tenant_id
    ):
        posting, _ = await gap_service.store_posting(
            tenant_id=operator_tenant_id,
            posting_text="Kubernetes required.",
            source="greenhouse",
            external_id="atomic-1",
            company_slug="acme",
            record_event="new",
        )
        assert posting is not None

        events = await _pending_events(session_factory)
        assert len(events) == 1
        assert events[0].event_type == "posting_changed"
        assert events[0].payload["posting_id"] == posting.id
        assert events[0].payload["status"] == "new"
        assert events[0].payload["content_hash"] == posting.content_hash

    async def test_no_event_recorded_when_caller_raises_none(
        self, gap_service, session_factory, operator_tenant_id
    ):
        """`record_event=None` is the pasted-posting path: a posting stored
        through the API raises no PostingChanged, so the relay has nothing to
        publish for it."""
        posting, _ = await gap_service.store_posting(
            tenant_id=operator_tenant_id,
            posting_text="A pasted posting.",
        )
        assert posting is not None
        assert await _pending_events(session_factory) == []

    async def test_failed_posting_write_leaves_no_outbox_row(
        self, gap_repo, session_factory, operator_tenant_id
    ):
        """The atomicity guarantee itself: if the posting's write fails, the
        outbox row must not survive it.

        Forced with a tenant_id that violates the FK to `users` — nothing in
        the ORM defaults that away, unlike the timestamp columns. Both
        statements share one transaction, so the outbox insert must roll back
        with the posting's.
        """
        missing_tenant = TenantId(999_999)
        now = datetime.now(UTC)
        row = JobPostingRow(
            source="greenhouse",
            external_id="doomed-1",
            company_slug="acme",
            company="",
            title="Eng",
            url="",
            content_hash="deadbeef" * 8,
            # Set explicitly, as the real caller does: the upsert branch reads
            # these out of the built `values` dict, and the ORM's column
            # defaults do not apply until flush.
            first_seen_at=now,
            last_seen_at=now,
        )
        with pytest.raises(IntegrityError):
            await gap_repo.upsert_posting(
                posting=row,
                tenant_id=missing_tenant,
                outbox_event={
                    "event_type": "posting_changed",
                    "payload": {
                        "tenant_id": int(missing_tenant),
                        "status": "new",
                        "content_hash": "deadbeef" * 8,
                    },
                },
            )

        assert await _all_events(session_factory) == []


class _SpyPublisher:
    def __init__(self, fail: bool = False):
        self.published = []
        self._fail = fail

    async def publish(self, event):
        if self._fail:
            raise RuntimeError("simulated publish failure")
        self.published.append(event)


class TestRelay:
    async def test_pending_events_publish_and_get_stamped(
        self, gap_service, gap_repo, session_factory, operator_tenant_id, monkeypatch
    ):
        from services.portfolio import refresh_trigger

        await gap_service.store_posting(
            tenant_id=operator_tenant_id,
            posting_text="Kubernetes required.",
            source="greenhouse",
            external_id="relay-1",
            company_slug="acme",
            record_event="new",
        )
        publisher = _SpyPublisher()
        monkeypatch.setattr(gap_service, "_publisher", publisher)
        refresh_trigger.app.state.gap_service = gap_service

        result = await refresh_trigger.dispatch_outbox()

        assert result["claimed"] == 1
        assert result["published"] == 1
        assert len(publisher.published) == 1
        assert await _pending_events(session_factory) == []

    async def test_publish_failure_leaves_the_event_pending(
        self, gap_service, session_factory, operator_tenant_id, monkeypatch
    ):
        """A failed publish must stay retryable — that is the whole reason the
        event is a durable row rather than a fire-and-forget call."""
        from services.portfolio import refresh_trigger

        await gap_service.store_posting(
            tenant_id=operator_tenant_id,
            posting_text="Terraform required.",
            source="greenhouse",
            external_id="relay-fail-1",
            company_slug="acme",
            record_event="new",
        )
        monkeypatch.setattr(gap_service, "_publisher", _SpyPublisher(fail=True))
        refresh_trigger.app.state.gap_service = gap_service

        result = await refresh_trigger.dispatch_outbox()

        assert result["published"] == 0
        assert len(await _pending_events(session_factory)) == 1

    async def test_concurrent_claims_do_not_double_publish(
        self, gap_service, gap_repo, session_factory, operator_tenant_id
    ):
        """`FOR UPDATE SKIP LOCKED` is what makes overlapping relay runs safe.
        A second claim held open against the first must take different rows,
        not the same ones — otherwise one event publishes twice."""
        for n in range(4):
            await gap_service.store_posting(
                tenant_id=operator_tenant_id,
                posting_text=f"Posting {n}.",
                source="greenhouse",
                external_id=f"concurrent-{n}",
                company_slug="acme",
                record_event="new",
            )

        # Hold the first claim's transaction open while the second one runs,
        # which is exactly the overlap a 1-minute scheduler can produce.
        async with session_factory() as first_session:
            async with first_session.begin():
                first = (
                    (
                        await first_session.execute(
                            select(EventOutboxRow)
                            .where(EventOutboxRow.published_at.is_(None))
                            .order_by(EventOutboxRow.id)
                            .limit(2)
                            .with_for_update(skip_locked=True)
                        )
                    )
                    .scalars()
                    .all()
                )
                second = await gap_repo.claim_pending_events(limit=2)

                first_ids = {row.id for row in first}
                second_ids = {row.id for row in second}
                assert len(first_ids) == 2
                assert len(second_ids) == 2
                assert first_ids.isdisjoint(second_ids)

    async def test_prune_deletes_only_long_published_rows(
        self, gap_service, gap_repo, session_factory, operator_tenant_id
    ):
        """Retention keeps the outbox an audit trail without unbounded growth.
        A pending row is a delivery still owed, so age must never collect it."""
        await gap_service.store_posting(
            tenant_id=operator_tenant_id,
            posting_text="Old news.",
            source="greenhouse",
            external_id="prune-1",
            company_slug="acme",
            record_event="new",
        )
        await gap_service.store_posting(
            tenant_id=operator_tenant_id,
            posting_text="Still pending.",
            source="greenhouse",
            external_id="prune-2",
            company_slug="acme",
            record_event="new",
        )
        events = await _pending_events(session_factory)
        assert len(events) == 2

        # Backdate one as published well past the retention window.
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "UPDATE event_outbox SET published_at = now() - interval "
                        "'30 days' WHERE id = :id"
                    ),
                    {"id": events[0].id},
                )

        pruned = await gap_repo.prune_published_events()

        assert pruned == 1
        remaining = await _all_events(session_factory)
        assert [row.id for row in remaining] == [events[1].id]
