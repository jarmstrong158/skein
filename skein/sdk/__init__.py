"""Internal Skein client helper.

NOT part of the v1 public API. Used by `skein demo` to drive the toy
3-agent workflow against a running Skein instance. The supported
integration path is the HTTP webhook (POST /trace/ingest) — instrument
your agent code to fire that yourself, or front it with a proxy.

For decorator-based cross-protocol instrumentation, prefer AOP
(aop-protocol). For enterprise observability backends, rely on A2A's
native OpenTelemetry trace propagation.

May be promoted to a public API in v1.2+ if user demand warrants it.
"""

from .client import (
    SkeinClient,
    get_client,
    install,
    send,
    send_agent_card,
)

__all__ = ["SkeinClient", "install", "send", "send_agent_card", "get_client"]
