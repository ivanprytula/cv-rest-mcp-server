import json
from pathlib import Path

import pytest
from google.cloud.exceptions import NotFound

from services.portfolio.cv_source import CvSource, parse_gcs_uri


class FakeBlob:
    def __init__(self, payload: str | None, generation: int = 1):
        self._payload = payload  # None = object does not exist yet
        self.generation = generation
        self.reload_calls = 0

    def reload(self):
        self.reload_calls += 1
        if self._payload is None:
            raise NotFound("no such object")
        return None

    def download_as_text(self) -> str:
        if self._payload is None:
            raise NotFound("no such object")
        return self._payload

    def publish(self, text: str):
        """Simulate uploading a new version of the object."""
        self._payload = text
        self.generation += 1


class FakeBucket:
    def __init__(self, blob: FakeBlob):
        self._blob = blob

    def blob(self, name: str) -> FakeBlob:
        return self._blob


class FakeClient:
    def __init__(self, blob: FakeBlob):
        self._bucket = FakeBucket(blob)

    def bucket(self, name: str) -> FakeBucket:
        assert name == "cv-bucket"
        return self._bucket


def _cv_json(name="Real Person") -> str:
    return json.dumps({"name": name, "title": "Engineer", "experience": []})


def _fallback(tmp_path) -> Path:
    path = tmp_path / "cv.example.json"
    path.write_text(json.dumps({"name": "Placeholder"}), encoding="utf-8")
    return path


def test_parse_gcs_uri_valid_and_invalid():
    assert parse_gcs_uri("gs://bkt/path/cv.json") == ("bkt", "path/cv.json")
    with pytest.raises(ValueError, match="Invalid CV_DATA_GCS_URI"):
        parse_gcs_uri("https://storage.googleapis.com/bkt/cv.json")


def test_local_file_mode_serves_file(synthetic_cv_path):
    source = CvSource(local_path=synthetic_cv_path)
    assert source.source_kind == "file"
    assert source.get()["name"] == "Jane Doe"


def test_local_missing_file_falls_back_to_placeholder(tmp_path):
    source = CvSource(
        local_path=tmp_path / "missing.json",
        fallback_path=_fallback(tmp_path),
    )
    assert source.source_kind == "placeholder"
    assert source.get()["name"] == "Placeholder"


def test_no_sources_at_all_raises(tmp_path):
    with pytest.raises(RuntimeError, match="no fallback CV available"):
        CvSource(local_path=tmp_path / "missing.json")


def test_gcs_initial_fetch_success(tmp_path):
    blob = FakeBlob(_cv_json())
    source = CvSource(
        gcs_uri="gs://cv-bucket/cv.json",
        storage_client=FakeClient(blob),
        fallback_path=_fallback(tmp_path),
    )
    assert source.source_kind == "gcs"
    assert source.get()["name"] == "Real Person"


def test_gcs_object_absent_boots_on_placeholder_then_hot_loads(tmp_path):
    blob = FakeBlob(None)
    clock = {"t": 1000.0}
    source = CvSource(
        gcs_uri="gs://cv-bucket/cv.json",
        refresh_seconds=30,
        storage_client=FakeClient(blob),
        fallback_path=_fallback(tmp_path),
        clock=lambda: clock["t"],
    )
    assert source.source_kind == "placeholder"

    # Within the TTL window nothing is re-checked.
    before = blob.reload_calls
    source.get()
    assert blob.reload_calls == before

    # Real cv.json is uploaded; after the TTL it swaps in automatically.
    blob.publish(_cv_json(name="Uploaded Person"))
    clock["t"] += 31
    assert source.get()["name"] == "Uploaded Person"
    assert source.source_kind == "gcs"


def test_gcs_refresh_failure_keeps_last_good_payload(tmp_path):
    blob = FakeBlob(_cv_json())
    clock = {"t": 0.0}
    source = CvSource(
        gcs_uri="gs://cv-bucket/cv.json",
        refresh_seconds=10,
        storage_client=FakeClient(blob),
        fallback_path=_fallback(tmp_path),
        clock=lambda: clock["t"],
    )
    blob.publish("not valid json {{")
    clock["t"] += 11
    assert source.get()["name"] == "Real Person"
    assert source.source_kind == "gcs"


def test_gcs_invalid_first_upload_stays_placeholder_until_fixed(tmp_path):
    blob = FakeBlob("{broken json")
    clock = {"t": 0.0}
    source = CvSource(
        gcs_uri="gs://cv-bucket/cv.json",
        refresh_seconds=10,
        storage_client=FakeClient(blob),
        fallback_path=_fallback(tmp_path),
        clock=lambda: clock["t"],
    )
    assert source.source_kind == "placeholder"

    blob.publish(_cv_json(name="Fixed Upload"))
    clock["t"] += 11
    assert source.get()["name"] == "Fixed Upload"
