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
"""

from __future__ import annotations

import json
import logging
from typing import Any


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
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "json",
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
