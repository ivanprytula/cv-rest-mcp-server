# Cloud CDN static assets + signed-URL uploads

Phase 1b edge capability. Two separate buckets with **opposite** access models,
kept apart deliberately (see ADR-021):

| Bucket | Module | Access | Serves |
|--------|--------|--------|--------|
| static | `modules/static_bucket` | **public read** (CDN origin) | Large static assets: images, JS, audio/video |
| uploads | `modules/uploads` | **fully private** (deny-public) | User avatars/photos, signed-URL only |

## Static assets: how the CDN actually works

`app.<apex>/assets/*` → a Cloud CDN **backend bucket** (`enable_cdn=true`,
`cache_mode="CACHE_ALL_STATIC"`), while `app.<apex>/` stays on the `spa-origin`
container. This is prefix routing **inside one host**, not a separate `static.`
host, because a host is either container-or-bucket unless you add a path rule.

### CDN request flow

1. Browser requests `https://app.<apex>/assets/big-video.mp4`.
2. The URL-map's `path_matcher` for `app.<apex>` sees the `/assets/*` `path_rule`
   → routes to the backend bucket → Cloud CDN.
3. **Miss**: the CDN edge fetches the object from the GCS origin, serves it, and
   caches it at edge POPs.
4. **Hit**: the object is served straight from the nearest edge — origin GCS gets
   no request at all. This is where large/video content "feels" fast and cheap.

### Cache behaviour per object

- `CACHE_ALL_STATIC`: any object with an HTTP `Cache-Control` header is cached for
  that duration; objects without one get a default TTL. Set **long** `max-age`
  (e.g. `Cache-Control: public, max-age=31536000, immutable`) on hashed/versioned
  files (out.png → out.<sha>.png) and **short** `max-age` only on files that
  change in place.
- `X-Cache: HIT` / `X-Cache: MISS` on the response tells you whether the edge
  served it — the quickest way to *see* the CDN work.
- Cache key defaults to the URL. Fine for our use; set a custom cache key only if
  you must serve per-user variants (you should not — that belongs in the private
  bucket).

### Invalidate cached content

Releases after changing a file in place:

```bash
gcloud compute url-maps invalidate-cdn-cache cv-edge-url-map \
  --path /assets/ \
  --project <project>
```

Invalidating a prefix clears every object under it. Check the exact URL-map name
from `terraform output` / `google_compute_url_map.edge`.

## Private uploads: signed URL only

`uploads` bucket is `public_access_prevention="enforced"` — **no** anonymous
read/write, **no** CDN. The UI never holds credentials; the **api-core server**
mints short-lived V4 signed URLs.

### Upload flow (avatar example)

1. UI (authenticated) calls `POST /me/avatar/upload-url {content_type}` on api-core,
   with the `user_id` from the auth session (server-side, not client-provided).
2. Server checks allowed `write_prefixes`, computes a fresh object key:
   `avatars/{user_id}/{uuid}.{ext}`, generates a V4 signed **PUT** URL
   (`method="PUT"`, TTL e.g. 10 min, `content_type` pinned so the client cannot
   upload an arbitrary type), and returns `{upload_url, object_key}`.
3. UI `PUT`s the bytes to `upload_url`. Because the URL is object-scoped, a user
   cannot write to anyone else's `avatars/...` path.
4. Read: the profile endpoint issues a V4 signed **GET** URL (short TTL) so the
   image can be displayed without being publicly accessible; or api-core fetches
   the object server-side with its `objectAdmin` SA and streams it to the client.

### Key layout (privacy)

```
avatars/{user_id}/{uuid}.jpg
photos/{user_id}/{uuid}.png
```

The `request_id`/`uuid` component makes object keys unguessable even if the
prefix is known, so one user cannot enumerate another's files.

## Recipes (manual, until the endpoint ships)

For manual experimentation while the API endpoints are still being built:

```bash
# 1. install a large test asset into the static bucket
gsutil cp big-video.mp4 gs://myproj-static/assets/

#   -> hit it via https://app.example.com/assets/big-video.mp4
#   -> watch X-Cache flip MISS then HIT on repeat requests

# 2. mint a signed upload URL for the private bucket (needs app SA credentials)
python - <<'PY'
from google.cloud import storage
b = storage.Client().bucket("myproj-uploads")
url = b.blob("avatars/u-123/avatar.jpg").generate_signed_url(
    method="PUT", expiration=600, version="v4",
    content_type="image/jpeg",
)
print(url)
PY
```

GCP SDKs (`google-cloud-storage`, `google-auth`) will need to be added to
`pyproject.toml` as dev-deps when the real endpoint is written (Phase 1c).

## Security posture (enforced)

`scripts/ensure_deny_public.py` (pre-commit `terraform-deny-public`) fails if:

- any bucket that is **not** the allowlisted CDN origin lacks
  `public_access_prevention="enforced"` + uniform access;
- any bucket binds `allUsers`/`allAuthenticatedUsers` to a **write** role.

The CDN origin is the single allowlisted exception (public read-only). Tests:
`tests/test_deny_public.py`.
