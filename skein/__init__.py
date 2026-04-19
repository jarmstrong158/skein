"""Skein — local-first observability for A2A multi-agent message flows.

The supported public integration is the HTTP webhook (POST /trace/ingest).
The `skein.sdk` module exists as an internal helper used by `skein demo`
but is not part of the v1 public API. For decorator-based instrumentation
across multiple agent protocols, prefer AOP (aop-protocol). For
enterprise observability backends, A2A's native OTLP trace propagation
forwards directly to OpenTelemetry-compatible platforms.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
