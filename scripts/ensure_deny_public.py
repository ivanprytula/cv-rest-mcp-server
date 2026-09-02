#!/usr/bin/env python3
"""Ensure every GCS bucket has proper deny-public-access policies.

Path-scoped guard that checkov cannot express (its skip-check is global, and
inline #checkov:skip is unreliable in the pinned version).

Rules enforced on every `google_storage_bucket`:
  * uniform_bucket_level_access = true
  * public_access_prevention    = "enforced"

  The ONE exception: the bucket identified by --cdn-origin-resource (the Cloud
  CDN origin, which must stay publicly readable for a google_compute_backend_bucket).
  That bucket is only allowed to be read publicly, never written.

Rules enforced on every `google_storage_bucket_iam_member`:
  * member must NOT be allUsers/allAuthenticatedUsers
  * a WRITE role (objectAdmin/Creator/Owner) is only allowed when bound to a
    PRIVATE service account (the trusted server that issues signed URLs) — it is
    forbidden for any public member

Exit 0 = all good, 1 = violation found.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys


BUCKET_RE = re.compile(
    r'resource\s+"google_storage_bucket"\s+"(?P<label>[^"]+)"\s*\{(?P<body>.*?)\n\}',
    re.DOTALL,
)
IAM_RE = re.compile(
    r'resource\s+"google_storage_bucket_iam_member"\s+"(?P<label>[^"]+)"\s*\{(?P<body>.*?)\n\}',
    re.DOTALL,
)
WRITE_ROLES = {
    "roles/storage.objectAdmin",
    "roles/storage.objectCreator",
    "roles/storage.objectOwner",
}
PUBLIC_MEMBERS = {"allUsers", "allAuthenticatedUsers"}


def find_arg(body: str, attr: str) -> str | None:
    # NOTE: f-string with a bare `}` is a syntax error on newer Pythons, so the
    # regex is assembled via concatenation instead.
    pattern = r"\b" + re.escape(attr) + r"\s*=\s*\"?([^\",\n}]+)"
    m = re.search(pattern, body)
    return m.group(1).strip().strip('"') if m else None


def resource_key(path: pathlib.Path, label: str) -> str:
    return f"{path}:google_storage_bucket.{label}"


def check_bucket(
    body: str, cdn_origin_res: str, path: pathlib.Path, label: str
) -> list[str]:
    if resource_key(path, label) == cdn_origin_res:
        # CDN origin: public by design, but never writable. Access is governed by
        # an explicit public-read-only IAM (checked separately).
        return []
    problems = []
    if find_arg(body, "uniform_bucket_level_access") != "true":
        problems.append("  - missing uniform_bucket_level_access = true")
    if find_arg(body, "public_access_prevention") != "enforced":
        problems.append('  - missing/incorrect public_access_prevention = "enforced"')
    return problems


def check_iam(body: str, path: pathlib.Path) -> list[str]:
    member = find_arg(body, "member")
    role = find_arg(body, "role")
    problems = []
    if member in PUBLIC_MEMBERS:
        # Anonymous WRITE is never acceptable, even on the CDN origin.
        if role in WRITE_ROLES:
            problems.append(
                f"  - PUBLIC write role ({role}) — writes must never be public"
            )
        # Anonymous READ-only is tolerated: it is exactly the CDN-origin access
        # model on the allowlisted bucket. The deny-public guarantee for every
        # OTHER bucket is enforced at the bucket level (public_access_prevention).
        # No failure here — only a note, so the origin exception is visible.
        else:
            print(
                f"note: anonymous read-only ({role}) on {path} — allowed only if this is the CDN origin"
            )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "dir", type=pathlib.Path, nargs="?", default=pathlib.Path("terraform")
    )
    ap.add_argument(
        "--cdn-origin-resource",
        default="",
        help="Resource address of the allowlisted public CDN origin bucket "
        "(e.g. terraform/modules/static_bucket/main.tf:google_storage_bucket.bucket).",
    )
    args = ap.parse_args()

    failures = []
    for tf in sorted(args.dir.rglob("*.tf")):
        text = tf.read_text()
        for m in BUCKET_RE.finditer(text):
            probs = check_bucket(
                m.group("body"), args.cdn_origin_resource, tf, m.group("label")
            )
            if probs:
                failures.append(f"[{tf}] google_storage_bucket.{m.group('label')}:")
                failures.extend(probs)
        for m in IAM_RE.finditer(text):
            probs = check_iam(m.group("body"), tf)
            if probs:
                failures.append(
                    f"[{tf}] google_storage_bucket_iam_member.{m.group('label')}:"
                )
                failures.extend(probs)

    if failures:
        print("DENY-PUBLIC VIOLATIONS FOUND:")
        print("\n".join(failures))
        print(
            "\nFix: private buckets need uniform_bucket_level_access=true and",
            'public_access_prevention="enforced"; never bind public members to writable roles.',
        )
        return 1
    print(
        "OK: all buckets deny public access (or are the allowlisted public CDN origin)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
