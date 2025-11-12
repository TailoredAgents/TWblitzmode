"""
FastAPI correlation-aware logging middleware (example)

Usage (in new repo):
    from examples.api.logging_middleware import logging_middleware, setup_json_logging
    setup_json_logging()
    app.middleware("http")(logging_middleware)
"""
from __future__ import annotations
import json
import logging
import os
import time
import uuid
from typing import Callable
from fastapi import Request, Response


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach extra fields if present
        for key in ("corr_id", "route", "method", "status", "latency_ms", "tenant_id", "org_id", "user_id", "service", "version"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["error_class"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


def setup_json_logging() -> None:
    fmt = os.getenv("LOG_FORMAT", "json").lower()
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level)
    if fmt == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
        root.addHandler(handler)


async def logging_middleware(request: Request, call_next: Callable[[Request], Response]) -> Response:
    logger = logging.getLogger("api")
    # Correlation Id
    corr_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    request.state.corr_id = corr_id

    # Timing
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Log error with corr_id and propagate
        logger.exception("unhandled_exception", extra={
            "corr_id": corr_id,
            "route": request.url.path,
            "method": request.method,
        })
        raise
    finally:
        elapsed_ms = int((time.perf_counter() - start) * 1000)

    # Structured request log
    logger.info(
        "request_completed",
        extra={
            "corr_id": corr_id,
            "route": request.url.path,
            "method": request.method,
            "status": getattr(response, "status_code", None),
            "latency_ms": elapsed_ms,
            "service": os.getenv("SERVICE_NAME", "link-api"),
            "version": os.getenv("SERVICE_VERSION", "dev"),
        },
    )
    # Echo corr id back to client
    response.headers["X-Correlation-Id"] = corr_id
    return response

