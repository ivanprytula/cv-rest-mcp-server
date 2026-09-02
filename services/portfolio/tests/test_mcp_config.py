"""MCP client tab config: bundled data validity, loader errors, landing render."""

import json

import pytest

from services.portfolio.routes import (
    MCP_CLIENTS_PATH,
    _client_mcp_configs,
    load_mcp_clients,
)


pytestmark = pytest.mark.usefixtures("override_pdf_service")


def test_bundled_config_is_valid_and_complete():
    clients = load_mcp_clients(MCP_CLIENTS_PATH)
    ids = [c["id"] for c in clients]
    assert len(ids) >= 4
    assert len(ids) == len(set(ids)), "client ids must be unique"
    for client in clients:
        assert "{mcp_url}" in client["config_template"]
        assert client["check"]["fetch_url"].startswith("https://")
        assert client["check"]["markers"]


def test_substitution_yields_parseable_configs():
    configs = _client_mcp_configs("http://example.test:1234/mcp")
    for client in configs:
        template = client["config_template"]
        assert "{mcp_url}" not in template
        assert "http://example.test:1234/mcp" in template
        if client["id"] != "codex":  # Codex ships TOML, everything else JSON
            json.loads(template)


def test_missing_file_raises(tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        load_mcp_clients(tmp_path / "nope.json")


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        load_mcp_clients(path)


def test_entry_missing_keys_raises(tmp_path):
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps([{"id": "x"}]), encoding="utf-8")
    with pytest.raises(RuntimeError, match="missing keys"):
        load_mcp_clients(path)


async def test_landing_renders_tabs_with_verified_stamps(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert 'role="tab"' in r.text
    assert "✓ verified 20" in r.text
    assert "mcp_servers.cv-rest-mcp-server" in r.text  # Codex TOML snippet present
