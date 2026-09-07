"""Tracked boards: CRUD, kind/field validation, and the refresh trigger's
active-only, API-backed-only filtering."""

import pytest
from fastapi import status


BOARDS = "/api/v1/tracked-boards"


@pytest.fixture
async def admin_client(auth_client):
    resp = await auth_client.post(
        "/api/v1/auth/token",
        json={"username": "operator", "password": "correct-password"},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    auth_client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return auth_client


def _greenhouse_board(slug="stripe", group=None):
    payload = {
        "kind": "greenhouse",
        "company_name": "Stripe",
        "company_slug": slug,
    }
    if group is not None:
        payload["group"] = group
    return payload


def _url_only_board(url="https://acme.com/careers", group=None):
    payload = {
        "kind": "url_only",
        "company_name": "Acme Corp",
        "url": url,
    }
    if group is not None:
        payload["group"] = group
    return payload


class TestCreateAndRead:
    async def test_create_api_backed_board_round_trips(self, admin_client):
        resp = await admin_client.post(BOARDS, json=_greenhouse_board())
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        body = resp.json()
        assert body["kind"] == "greenhouse"
        assert body["company_slug"] == "stripe"
        assert body["url"] is None
        assert body["active"] is True

        read = await admin_client.get(f"{BOARDS}/{body['id']}")
        assert read.status_code == status.HTTP_200_OK
        assert read.json()["company_name"] == "Stripe"

    async def test_create_url_only_board_round_trips(self, admin_client):
        resp = await admin_client.post(BOARDS, json=_url_only_board())
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        body = resp.json()
        assert body["kind"] == "url_only"
        assert body["company_slug"] is None
        assert body["url"] == "https://acme.com/careers"

    async def test_read_missing_board_is_404(self, admin_client):
        resp = await admin_client.get(f"{BOARDS}/999999")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_notes_round_trip_on_create(self, admin_client):
        payload = _url_only_board()
        payload["notes"] = "Redirects to a recruiting agency's Greenhouse board"
        resp = await admin_client.post(BOARDS, json=payload)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert (
            resp.json()["notes"]
            == "Redirects to a recruiting agency's Greenhouse board"
        )

    async def test_notes_default_to_null(self, admin_client):
        resp = await admin_client.post(BOARDS, json=_greenhouse_board())
        assert resp.json()["notes"] is None


class TestValidation:
    async def test_api_backed_kind_without_slug_is_rejected(self, admin_client):
        resp = await admin_client.post(
            BOARDS,
            json={"kind": "greenhouse", "company_name": "Stripe"},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_api_backed_kind_with_url_is_rejected(self, admin_client):
        resp = await admin_client.post(
            BOARDS,
            json={
                "kind": "greenhouse",
                "company_name": "Stripe",
                "company_slug": "stripe",
                "url": "https://stripe.com",
            },
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_url_only_kind_without_url_is_rejected(self, admin_client):
        resp = await admin_client.post(
            BOARDS,
            json={"kind": "url_only", "company_name": "Acme"},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_url_only_kind_with_slug_is_rejected(self, admin_client):
        resp = await admin_client.post(
            BOARDS,
            json={
                "kind": "url_only",
                "company_name": "Acme",
                "url": "https://acme.com",
                "company_slug": "acme",
            },
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_unknown_kind_is_rejected(self, admin_client):
        resp = await admin_client.post(
            BOARDS,
            json={
                "kind": "workday",
                "company_name": "Acme",
                "company_slug": "acme",
            },
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestUpdate:
    async def test_patch_updates_a_subset_of_fields(self, admin_client):
        created = (await admin_client.post(BOARDS, json=_greenhouse_board())).json()
        resp = await admin_client.patch(
            f"{BOARDS}/{created['id']}", json={"company_name": "Stripe Inc"}
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body["company_name"] == "Stripe Inc"
        assert body["company_slug"] == "stripe"  # untouched

    async def test_patch_can_set_notes(self, admin_client):
        created = (await admin_client.post(BOARDS, json=_url_only_board())).json()
        resp = await admin_client.patch(
            f"{BOARDS}/{created['id']}",
            json={"notes": "Turns out this has a JSON API after all"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["notes"] == "Turns out this has a JSON API after all"

    async def test_patch_can_deactivate_a_board(self, admin_client):
        created = (await admin_client.post(BOARDS, json=_greenhouse_board())).json()
        resp = await admin_client.patch(
            f"{BOARDS}/{created['id']}", json={"active": False}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["active"] is False

    async def test_patch_ignores_kind_since_the_schema_has_no_such_field(
        self, admin_client
    ):
        created = (await admin_client.post(BOARDS, json=_greenhouse_board())).json()
        resp = await admin_client.patch(
            f"{BOARDS}/{created['id']}",
            json={"kind": "url_only", "company_name": "Stripe"},
        )
        # TrackedBoardUpdate has no `kind` field at all, so FastAPI silently
        # drops the extra key rather than rejecting the request; the board's
        # kind must remain unchanged either way.
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["kind"] == "greenhouse"

    async def test_patch_missing_board_is_404(self, admin_client):
        resp = await admin_client.patch(f"{BOARDS}/999999", json={"active": False})
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestDelete:
    async def test_delete_removes_the_board(self, admin_client):
        created = (await admin_client.post(BOARDS, json=_greenhouse_board())).json()
        resp = await admin_client.delete(f"{BOARDS}/{created['id']}")
        assert resp.status_code == status.HTTP_204_NO_CONTENT

        after = await admin_client.get(f"{BOARDS}/{created['id']}")
        assert after.status_code == status.HTTP_404_NOT_FOUND

    async def test_delete_missing_board_is_404(self, admin_client):
        resp = await admin_client.delete(f"{BOARDS}/999999")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestListing:
    async def test_list_all_includes_inactive_by_default(self, admin_client):
        created = (await admin_client.post(BOARDS, json=_greenhouse_board())).json()
        await admin_client.patch(f"{BOARDS}/{created['id']}", json={"active": False})

        body = (await admin_client.get(BOARDS)).json()
        assert any(b["id"] == created["id"] for b in body)

    async def test_list_active_only_excludes_disabled_boards(self, admin_client):
        created = (await admin_client.post(BOARDS, json=_greenhouse_board())).json()
        await admin_client.patch(f"{BOARDS}/{created['id']}", json={"active": False})

        body = (await admin_client.get(BOARDS, params={"active_only": "true"})).json()
        assert not any(b["id"] == created["id"] for b in body)


class TestGroups:
    async def test_group_round_trips_on_create(self, admin_client):
        resp = await admin_client.post(BOARDS, json=_greenhouse_board(group="priority"))
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()["group"] == "priority"

    async def test_group_defaults_to_null(self, admin_client):
        resp = await admin_client.post(BOARDS, json=_greenhouse_board())
        assert resp.json()["group"] is None

    async def test_patch_can_set_group(self, admin_client):
        created = (await admin_client.post(BOARDS, json=_greenhouse_board())).json()
        resp = await admin_client.patch(
            f"{BOARDS}/{created['id']}", json={"group": "fintech"}
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["group"] == "fintech"

    async def test_list_filters_by_group(self, admin_client):
        priority = (
            await admin_client.post(
                BOARDS, json=_greenhouse_board(slug="stripe", group="priority")
            )
        ).json()
        ungrouped = (
            await admin_client.post(BOARDS, json=_greenhouse_board(slug="lyft"))
        ).json()

        filtered = (await admin_client.get(BOARDS, params={"group": "priority"})).json()
        assert any(b["id"] == priority["id"] for b in filtered)
        assert not any(b["id"] == ungrouped["id"] for b in filtered)

    async def test_list_without_group_param_returns_every_group(self, admin_client):
        priority = (
            await admin_client.post(
                BOARDS, json=_greenhouse_board(slug="stripe", group="priority")
            )
        ).json()
        ungrouped = (
            await admin_client.post(BOARDS, json=_greenhouse_board(slug="lyft"))
        ).json()

        body = (await admin_client.get(BOARDS)).json()
        assert any(b["id"] == priority["id"] for b in body)
        assert any(b["id"] == ungrouped["id"] for b in body)


class TestAuth:
    @pytest.mark.parametrize(
        ("method", "path"),
        [("GET", BOARDS), ("POST", BOARDS)],
    )
    async def test_unauthenticated_is_401(self, client, method, path):
        resp = await client.request(method, path, headers={"Authorization": ""})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
