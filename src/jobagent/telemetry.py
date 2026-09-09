"""OpenTelemetry -> Phoenix wiring (observability milestone).

One lazy initializer shared by the CLI commands and the future nightly
graph, so every run of a real pipeline path emits a trace:

  - emits to the local Phoenix collector (OTLP gRPC, proven by
    scripts/smoke.py) under the default project, so traces accumulate in
    the same dashboard view as the smoke span
  - never raises: if Phoenix or OpenTelemetry is unavailable the spans
    degrade to no-ops, so tracing can never break the pipeline
  - disable with JOBAGENT_OTEL=0; override the collector with
    JOBAGENT_OTEL_ENDPOINT (default http://127.0.0.1:4317)

Only manual spans are recorded (instrumentation lives in the pipeline
code itself); no third-party auto-instrumentors are loaded.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from typing import Any, Self

_OTEL_ENDPOINT = os.environ.get("JOBAGENT_OTEL_ENDPOINT", "http://127.0.0.1:4317")
_init_attempted = False
_provider = None


def _register() -> None:
    """Idempotent provider registration; failures degrade to no-op spans.

    Mirrors scripts/smoke.py exactly (endpoint-only call, capture the
    returned provider): register() takes no service_name kwarg, and relying
    on it raised a TypeError here before -- silently caught, so spans went
    nowhere. Capturing the provider makes tracer() deterministic either way.
    """
    global _init_attempted, _provider
    if _init_attempted:
        return
    _init_attempted = True
    if os.environ.get("JOBAGENT_OTEL", "1") == "0":
        return
    try:
        from phoenix.otel import register

        _provider = register(endpoint=_OTEL_ENDPOINT, verbose=False)
    except Exception:  # noqa: BLE001 - tracing must never break the pipeline
        return


class _NullSpan:
    """Drop-in for when OpenTelemetry itself is unavailable."""

    def set_attribute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_status(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def record_exception(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def end(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _NullTracer:
    """Drop-in tracer when OpenTelemetry is not importable."""

    def start_span(self, *_args: Any, **_kwargs: Any) -> _NullSpan:
        return _NullSpan()

    def start_as_current_span(self, *_args: Any, **_kwargs: Any) -> _NullSpan:
        return _NullSpan()


def tracer() -> Any:
    """Return the jobsearch-agent tracer (no-op when tracing is off)."""
    _register()
    if _provider is not None:
        return _provider.get_tracer("jobsearch-agent")
    try:
        from opentelemetry import trace

        return trace.get_tracer("jobsearch-agent")
    except ImportError:
        return _NullTracer()


def _mark_error(sp: Any, message: str) -> None:
    """Record an ERROR status on the span when OpenTelemetry is present."""
    try:
        from opentelemetry.trace import Status, StatusCode
    except ImportError:
        return
    sp.set_status(Status(StatusCode.ERROR, message))


@contextlib.contextmanager
def span(name: str, attrs: dict[str, Any] | None = None) -> Iterator[Any]:
    """Context-managed span: sets attrs on entry, elapsed_ms on exit.

    Exceptions are recorded on the span (status ERROR) and re-raised, so
    existing error handling in callers is unchanged.
    """
    t0 = time.monotonic()
    with tracer().start_as_current_span(name) as sp:
        for key, value in (attrs or {}).items():
            sp.set_attribute(key, value)
        try:
            yield sp
        except Exception as exc:
            _mark_error(sp, str(exc)[:500])
            raise
        finally:
            sp.set_attribute("elapsed_ms", round((time.monotonic() - t0) * 1000, 1))
