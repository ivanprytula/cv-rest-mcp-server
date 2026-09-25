import pytest
from fastapi import status


async def test_culture_bingo_page(client):
    resp = await client.get("/culture-bingo")
    assert resp.status_code == status.HTTP_200_OK
    assert "text/html" in resp.headers["content-type"]
    assert "Company Culture Bingo" in resp.text
    assert 'id="grid"' in resp.text
    assert 'aria-live="polite"' in resp.text


async def test_culture_bingo_page_links_back(client):
    resp = await client.get("/culture-bingo")
    assert resp.status_code == status.HTTP_200_OK
    assert 'href="' in resp.text
    assert "Back to portfolio" in resp.text


async def test_culture_bingo_cards_page_zero(client):
    resp = await client.get("/api/v1/culture-bingo/cards?page=0")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["page"] == 0
    assert "total_pages" in data
    assert "total_cards" in data
    assert "page_size" in data
    assert isinstance(data["cells"], list)
    assert 1 <= len(data["cells"]) <= data["page_size"]


async def test_culture_bingo_cards_page_size(client):
    resp = await client.get("/api/v1/culture-bingo/cards?page=0")
    data = resp.json()
    # Page 0 should have exactly PAGE_SIZE cards (if total >= PAGE_SIZE)
    if data["total_cards"] >= data["page_size"]:
        assert len(data["cells"]) == data["page_size"]


async def test_culture_bingo_cards_fixed_order(client):
    """Same page fetched twice returns identical card order (no shuffle)."""
    resp1 = await client.get("/api/v1/culture-bingo/cards?page=0")
    resp2 = await client.get("/api/v1/culture-bingo/cards?page=0")
    assert [c["id"] for c in resp1.json()["cells"]] == [
        c["id"] for c in resp2.json()["cells"]
    ]


async def test_culture_bingo_cards_pages_are_disjoint(client):
    """Page 0 and page 1 contain different cards."""
    r0 = await client.get("/api/v1/culture-bingo/cards?page=0")
    r1 = await client.get("/api/v1/culture-bingo/cards?page=1")
    if r0.json()["total_pages"] < 2:
        pytest.skip("Not enough cards for two pages")
    ids0 = {c["id"] for c in r0.json()["cells"]}
    ids1 = {c["id"] for c in r1.json()["cells"]}
    assert ids0.isdisjoint(ids1)


async def test_culture_bingo_cards_out_of_range(client):
    """A page beyond the last returns an empty cells list, not an error."""
    resp = await client.get("/api/v1/culture-bingo/cards?page=9999")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["cells"] == []


async def test_culture_bingo_cards_negative_page_rejected(client):
    resp = await client.get("/api/v1/culture-bingo/cards?page=-1")
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_security_headers_present(client):
    resp = await client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "content-security-policy" in resp.headers
