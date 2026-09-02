"""Tests for the path-scoped deny-public bucket guard (scripts/ensure_deny_public.py)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ensure_deny_public.py"

PRIVATE_OK = """
resource "google_storage_bucket" "uploads" {
  name                        = "my-uploads"
  location                    = "EU"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  versioning { enabled = true }
}
"""

PRIVATE_MISSING_ENFORCEMENT = """
resource "google_storage_bucket" "uploads" {
  name                        = "my-uploads"
  location                    = "EU"
  uniform_bucket_level_access = true
}
"""

PUBLIC_WRITE = """
resource "google_storage_bucket_iam_member" "bad" {
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectCreator"
  member = "allUsers"
}
"""

CDN_ORIGIN = """
resource "google_storage_bucket" "bucket" {
  name                        = "my-static"
  location                    = "EU"
  uniform_bucket_level_access = true
}
resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.bucket.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}
"""


def run_guard(directory: Path, cdn_origin: str = "") -> int:
    cmd = [sys.executable, str(SCRIPT), str(directory)]
    if cdn_origin:
        cmd += ["--cdn-origin-resource", cdn_origin]
    return subprocess.run(cmd, capture_output=True, text=True).returncode


def write_block(tmp_path: Path, content: str, name: str = "b.tf") -> Path:
    d = tmp_path / "mod"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(content)
    return p


@pytest.mark.needs_script
def test_private_bucket_enforced_passes(tmp_path: Path) -> None:
    write_block(tmp_path, PRIVATE_OK)
    assert run_guard(tmp_path) == 0


@pytest.mark.needs_script
def test_missing_enforcement_fails(tmp_path: Path) -> None:
    write_block(tmp_path, PRIVATE_MISSING_ENFORCEMENT)
    assert run_guard(tmp_path) == 1


@pytest.mark.needs_script
def test_anonymous_write_fails(tmp_path: Path) -> None:
    # A private bucket + a public write role must be rejected even if the
    # origin allowlist is supplied.
    write_block(tmp_path, PRIVATE_OK + PUBLIC_WRITE)
    assert (
        run_guard(
            tmp_path, cdn_origin=f"{tmp_path}/mod/b.tf:google_storage_bucket.uploads"
        )
        == 1
    )


@pytest.mark.needs_script
def test_cdn_origin_read_only_allowed(tmp_path: Path) -> None:
    write_block(tmp_path, CDN_ORIGIN)
    addr = f"{tmp_path}/mod/b.tf:google_storage_bucket.bucket"
    # Without the allowlist the CDN origin must FAIL (it is not enforced)...
    assert run_guard(tmp_path) == 1
    # ...with the allowlist it passes (public read-only = the CDN-origin model).
    assert run_guard(tmp_path, cdn_origin=addr) == 0
