"""Compute SHA-256 hash of FastAPI /docs inline script for CSP.

Usage (requires dev server on :8080):
    python scripts/csp_swaggerui_hash.py

Paste the output into app/main.py _CSP_DIRECTIVE script-src.
"""

import base64
import hashlib
import re
import sys
import urllib.request


url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080/docs"

try:
    with urllib.request.urlopen(url) as resp:
        html = resp.read().decode()
except Exception as exc:
    sys.exit(f"Cannot fetch {url}: {exc}\nIs the dev server running? (just dev)")

scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
if not scripts:
    sys.exit("No inline <script> found in /docs page")

for s in scripts:
    digest = hashlib.sha256(s.encode()).digest()
    print(f"'sha256-{base64.b64encode(digest).decode()}'")
