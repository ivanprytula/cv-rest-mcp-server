"""Structured (JSON-lines) logging, shared by every backend entrypoint
(api-core's `services.portfolio.main`, api-games's `services.games.main`,
and the smaller portfolio workers) so a log-shipping sidecar (Promtail,
Fluentd) or `gcloud logging` sees one consistent shape across services.

Cloud Run maps stderr -> ERROR for every line regardless of the record's
real level, so app logs go to stdout instead. One JSON object per line,
ready for Prometheus/ELK ingestion without a text-log parser.

Each entrypoint calls `configure_logging()` (for `python -m
services.<x>.main`) or passes `build_log_config()` to uvicorn's CLI as
`--log-config` (for local `--reload` dev servers — see justfile). Uvicorn's
own `configure_logging()` runs *after* importing the app and
unconditionally resets the root logger, silently swallowing every
`logger.info`/`logger.warning` call under `--reload` unless told what to
configure instead of overwriting.

`extra_loggers` lets a service adapt the shared base without copying it:
api-core's WeasyPrint render pipeline is noisy at INFO, api-games has no
such pipeline, so only api-core passes an override for it.

`TraceIdFilter` stamps the in-flight request's correlation id onto every
record, so one query returns every line a request produced across services.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from shared.tracing import current_trace_id


class JsonFormatter(logging.Formatter):
    """Renders one `logging.LogRecord` as one JSON line."""

    _RESERVED = logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys() | {
        "message",
        "asctime",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # logger.info("msg", extra={"input_tokens": 1}) surfaces as its own
        # top-level field — the whole point of structured logging over a
        # formatted string a log pipeline would need to re-parse.
        for key, value in record.__dict__.items():
            if key not in self._RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TraceIdFilter(logging.Filter):
    """Stamps the in-flight request's correlation id onto every record.

    Attached to the *handler* rather than a logger: uvicorn's loggers set
    `propagate: False`, so a logger-level filter would miss their records.

    On Cloud Run, `logging.googleapis.com/trace` is the magic field that
    makes Cloud Logging join the line to the trace the platform already
    recorded, which is what turns `trace_id` into a clickable trace rather
    than just a string to grep. It needs the project id, and Cloud Run does
    *not* inject one (it sets `K_SERVICE`/`K_REVISION`/`K_CONFIGURATION`),
    so `GOOGLE_CLOUD_PROJECT` is set explicitly in terraform.tfvars. Unset
    locally and in tests, which is exactly the wanted no-op: dev logs carry
    the bare `trace_id` and no GCP-specific field.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if trace_id := current_trace_id():
            record.trace_id = trace_id
            if project := os.getenv("GOOGLE_CLOUD_PROJECT"):
                setattr(
                    record,
                    "logging.googleapis.com/trace",
                    f"projects/{project}/traces/{trace_id}",
                )
        return True


def build_log_config(
    extra_loggers: dict[str, dict[str, Any]] | None = None,
    log_level: str = "INFO",
) -> dict:
    """Build the logging config dict for use with dictConfig or uvicorn's --log-config."""
    log_level = log_level.upper()
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": f"{__name__}.JsonFormatter"},
        },
        "filters": {
            "trace_id": {"()": f"{__name__}.TraceIdFilter"},
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "filters": ["trace_id"],
                "stream": "ext://sys.stdout",
            },
        },
        "root": {"level": log_level, "handlers": ["default"]},
        "loggers": {
            "uvicorn": {
                "level": "INFO",
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {
                "level": "INFO",
                "handlers": ["default"],
                "propagate": False,
            },
        },
    }
    if extra_loggers:
        config["loggers"].update(extra_loggers)
    return config


def configure_logging(
    extra_loggers: dict[str, dict[str, Any]] | None = None,
    log_level: str = "INFO",
) -> None:
    """Apply logging config to the current process via dictConfig."""
    import logging.config

    logging.config.dictConfig(build_log_config(extra_loggers, log_level))
