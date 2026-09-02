import json
import logging
import re
import threading
import time
from pathlib import Path

from google.api_core.exceptions import NotFound
from google.cloud import storage

from services.portfolio.cv_data import load_cv_data, validate_cv_payload


logger = logging.getLogger(__name__)

_GCS_URI_RE = re.compile(r"^gs://([^/]+)/(.+)$")


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    match = _GCS_URI_RE.match(uri)
    if not match:
        raise ValueError(
            f"Invalid CV_DATA_GCS_URI: {uri!r}. Expected gs://<bucket>/<object>"
        )
    return match.group(1), match.group(2)


class CvSource:
    """Resolves the active CV document: GCS object, local file, or placeholder.

    Boot always succeeds as long as *some* payload is servable:

    - GCS mode: the object is fetched; if absent (or unreadable) the service
      boots on ``fallback_path`` (cv.example.json) and keeps polling —
      uploading a real cv.json goes live without a redeploy.
    - File mode: a missing local file falls back to the same placeholder.

    Runtime refreshes are best-effort: failures keep the last good payload
    and log a warning.  ``source_kind`` reports which state is being served:
    "gcs", "file", or "placeholder".
    """

    def __init__(
        self,
        *,
        local_path: Path | None = None,
        gcs_uri: str = "",
        refresh_seconds: int = 30,
        fallback_path: Path | None = None,
        storage_client=None,
        clock=time.monotonic,
    ) -> None:
        self._gcs_uri = gcs_uri or ""
        self._refresh_seconds = max(0, refresh_seconds)
        self._fallback_path = fallback_path
        self._clock = clock
        self._lock = threading.Lock()
        self._checked_at: float = 0.0
        self._generation: int | None = None
        self._cv: dict = {}
        self.source_kind = "placeholder"
        self._blob = None

        if self._gcs_uri:
            bucket_name, object_name = parse_gcs_uri(self._gcs_uri)
            client = storage_client or storage.Client()
            self._blob = client.bucket(bucket_name).blob(object_name)
            try:
                self._generation, self._cv = self._fetch(self._blob)
                self.source_kind = "gcs"
                logger.info(
                    "CV source: gs://%s/%s (generation %s)",
                    bucket_name,
                    object_name,
                    self._generation,
                )
            except Exception as exc:
                self._fallback_or_raise(
                    f"CV object gs://{bucket_name}/{object_name} unavailable ({exc})"
                )
            finally:
                self._checked_at = self._clock()
        elif local_path is not None:
            try:
                self._cv = load_cv_data(local_path)
                self.source_kind = "file"
                logger.info("CV source: %s", local_path)
            except (FileNotFoundError, ValueError) as exc:
                self._fallback_or_raise(f"CV file {local_path} unusable ({exc})")
        else:
            raise ValueError("CvSource requires local_path or gcs_uri")

    def _fallback_or_raise(self, reason: str) -> None:
        if self._fallback_path is None:
            raise RuntimeError(f"{reason}; no fallback CV available") from None
        self._cv = load_cv_data(self._fallback_path)
        self.source_kind = "placeholder"
        logger.warning("%s; serving placeholder from %s", reason, self._fallback_path)

    def _fetch(self, blob) -> tuple[int, dict]:
        """Download and validate the GCS object; returns (generation, payload)."""
        blob.reload()  # metadata-only GET; refreshes blob.generation
        raw = json.loads(blob.download_as_text())
        return blob.generation, validate_cv_payload(raw)

    def get(self) -> dict:
        if self._blob is None:
            return self._cv

        now = self._clock()
        with self._lock:
            due = now - self._checked_at >= self._refresh_seconds
            self._checked_at = now
        if not due:
            return self._cv

        try:
            generation, cv = self._fetch(self._blob)
        except NotFound:
            logger.warning(
                "CV object %s not found; serving %s", self._gcs_uri, self.source_kind
            )
            return self._cv
        except Exception:
            logger.warning(
                "CV refresh from %s failed; serving last good payload",
                self._gcs_uri,
                exc_info=True,
            )
            return self._cv

        with self._lock:
            if generation != self._generation:
                logger.info(
                    "CV updated from %s (%s -> %s)",
                    self._gcs_uri,
                    self._generation,
                    generation,
                )
                self._generation = generation
                self._cv = cv
                self.source_kind = "gcs"
        return self._cv


def build_cv_source_from_settings() -> CvSource:
    from services.portfolio.constants import EXAMPLE_CV_PATH
    from services.portfolio.settings import settings

    return CvSource(
        local_path=settings.cv_data_path,
        gcs_uri=settings.cv_data_gcs_uri,
        refresh_seconds=settings.cv_refresh_seconds,
        fallback_path=EXAMPLE_CV_PATH,
    )
