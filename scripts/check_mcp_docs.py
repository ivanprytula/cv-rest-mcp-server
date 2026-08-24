#!/usr/bin/env python3
"""Drift-check MCP client doc sources listed in config/mcp_clients.json.

Fetches each client's documented source (markdown/HTML) and asserts that the
config markers our landing-page snippets rely on are still present. Designed
for the monthly `mcp-docs-drift` GitHub Actions workflow:

- default:  check only, print a PASS/FAIL table, exit 1 on any drift
- --bump:   after a clean check, rewrite each "verified" stamp to the current
            month so the workflow can commit the refresh

Stdlib only — runs on bare setup-python.
"""

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "mcp_clients.json"
REQUEST_TIMEOUT_S = 30
USER_AGENT = "cv-rest-mcp-server-docs-checker"


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        return response.read().decode("utf-8", errors="replace")


def check_client(client: dict) -> tuple[bool, str]:
    """Return (ok, detail) for one client's marker expectations."""
    source = client.get("check", {})
    url, markers = source.get("fetch_url"), source.get("markers")
    if not url or not markers:
        return False, "entry lacks check.fetch_url / check.markers"
    try:
        text = fetch(url)
    except Exception as exc:
        return False, f"fetch failed: {exc}"
    missing = [marker for marker in markers if marker not in text]
    if missing:
        return False, f"missing markers {missing} in {url}"
    return True, f"all {len(markers)} markers found"


def bump_stamps(path: Path) -> bool:
    """Rewrite every verified stamp to the current month; True when changed."""
    stamp = datetime.now(UTC).strftime("%Y-%m")
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for entry in data:
        if entry.get("verified") != stamp:
            entry["verified"] = stamp
            changed = True
    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bump",
        action="store_true",
        help="after a clean check, update verified stamps to the current month",
    )
    args = parser.parse_args()

    clients = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    results = [(client["id"], *check_client(client)) for client in clients]

    width = max(len(client_id) for client_id, *_ in results)
    for client_id, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {client_id.ljust(width)}  {detail}")

    failures = [client_id for client_id, ok, _ in results if not ok]
    if failures:
        print(f"\nDrift detected for: {', '.join(failures)}", file=sys.stderr)
        return 1

    if args.bump:
        if bump_stamps(CONFIG_PATH):
            print(f"verified stamps refreshed -> {datetime.now(UTC):%Y-%m}")
        else:
            print("verified stamps already current")

    print(f"\nAll {len(results)} doc sources match expected markers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
