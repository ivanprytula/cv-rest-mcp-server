import re

from fastapi import status


async def test_culture_bingo_page(client):
    resp = await client.get("/culture-bingo")
    assert resp.status_code == status.HTTP_200_OK
    assert "text/html" in resp.headers["content-type"]
    assert "Company Culture Bingo" in resp.text
    assert 'class="grid"' in resp.text
    assert 'aria-live="polite"' in resp.text


async def test_culture_bingo_content_endpoint(client):
    resp = await client.get("/api/v1/culture-bingo/content")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "title" in data
    assert "cells" in data
    assert isinstance(data["cells"], list)
    assert len(data["cells"]) > 0
    for cell in data["cells"]:
        assert "id" in cell
        assert "content" in cell


async def test_culture_bingo_content_cell_count_matches_grid(client):
    resp = await client.get("/api/v1/culture-bingo/content")
    data = resp.json()
    assert isinstance(data["cells"], list)
    assert len(data["cells"]) == data["settings"]["gridSize"] ** 2


async def test_culture_bingo_page_links_back(client):
    resp = await client.get("/culture-bingo")
    assert resp.status_code == status.HTTP_200_OK
    assert 'href="/"' in resp.text


async def test_culture_bingo_page_randomizes_cell_order(client):
    """Two page loads should produce different cell orderings."""
    ids_pattern = re.compile(r'data-id="([^"]+)"')
    resp1 = await client.get("/culture-bingo")
    resp2 = await client.get("/culture-bingo")
    order1 = ids_pattern.findall(resp1.text)
    order2 = ids_pattern.findall(resp2.text)
    assert order1 != order2


async def test_security_headers_present(client):
    resp = await client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "content-security-policy" in resp.headers
