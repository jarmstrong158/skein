"""Optional monkey-patch of the official `a2a-sdk` Python package.

Strategy: locate the SDK's request-sending and response-receiving choke points
and wrap them so every JSON-RPC payload also flows to Skein.

The `a2a-sdk` API is still moving; this module fails loud if the patch points
shift, so users notice rather than silently getting no traces. The explicit
`skein.send()` API remains the always-works escape hatch.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("skein.sdk.a2a_patch")


class PatchPointMissing(RuntimeError):
    """Raised when expected a2a-sdk attributes are not found."""


def install(client) -> None:
    """Apply the patch. `client` is a SkeinClient.

    Currently patches A2AClient.send_message / send_streaming_message if present.
    Tested against a2a-sdk versions exposing those methods.
    """
    try:
        import a2a  # type: ignore
    except ImportError as e:
        raise PatchPointMissing("a2a-sdk is not installed") from e

    patched_any = False

    # Try common locations across a2a-sdk versions.
    candidates = [
        ("a2a.client", "A2AClient"),
        ("a2a", "A2AClient"),
    ]
    cls = None
    for mod_name, attr in candidates:
        try:
            mod = __import__(mod_name, fromlist=[attr])
            cls = getattr(mod, attr, None)
            if cls is not None:
                break
        except ImportError:
            continue

    if cls is None:
        raise PatchPointMissing("Could not locate a2a-sdk A2AClient")

    for method_name in ("send_message", "send_streaming_message", "send"):
        original = getattr(cls, method_name, None)
        if original is None or getattr(original, "_skein_wrapped", False):
            continue

        def make_wrapper(orig):
            def wrapper(self, *args, **kwargs):
                # Best effort — extract payload arg if present
                payload = None
                if args and isinstance(args[0], dict):
                    payload = args[0]
                elif "request" in kwargs and isinstance(kwargs["request"], dict):
                    payload = kwargs["request"]
                if payload is not None:
                    try:
                        client.send(payload, direction="outbound")
                    except Exception as e:
                        log.warning("skein outbound capture failed: %s", e)
                result = orig(self, *args, **kwargs)
                if isinstance(result, dict):
                    try:
                        client.send(result, direction="inbound")
                    except Exception as e:
                        log.warning("skein inbound capture failed: %s", e)
                return result

            wrapper._skein_wrapped = True  # type: ignore[attr-defined]
            wrapper.__wrapped__ = orig  # type: ignore[attr-defined]
            return wrapper

        setattr(cls, method_name, make_wrapper(original))
        patched_any = True
        log.info("skein patched %s.%s", cls.__name__, method_name)

    if not patched_any:
        raise PatchPointMissing("No patchable methods found on A2AClient")
