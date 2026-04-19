"""Skein client — sends captured A2A payloads to the trace endpoint.

Designed to be best-effort: failures to reach the trace endpoint must NEVER
break the host application. All transport errors are swallowed and logged.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("skein.sdk")

DEFAULT_ENDPOINT = "http://127.0.0.1:5050"
DEFAULT_TIMEOUT = 1.0  # seconds — keep low so trace failures don't stall agents
DEFAULT_PROTOCOL_VERSION = "0.3.1"

_client: "SkeinClient | None" = None
_client_lock = threading.Lock()


class SkeinClient:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        protocol_version: str = DEFAULT_PROTOCOL_VERSION,
        raise_on_error: bool = False,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.raise_on_error = raise_on_error

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        url = f"{self.endpoint}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            if self.raise_on_error:
                raise
            log.warning("skein trace post to %s failed: %s", url, e)
            return None

    def send(
        self,
        payload: dict[str, Any],
        *,
        direction: str = "outbound",
        captured_at: str | None = None,
        protocol_version: str | None = None,
    ) -> dict[str, Any] | None:
        return self._post(
            "/trace/ingest",
            {
                "payload": payload,
                "direction": direction,
                "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
                "protocol_version": protocol_version or self.protocol_version,
            },
        )

    def send_agent_card(self, card: dict[str, Any]) -> dict[str, Any] | None:
        return self._post("/trace/agent_card", card)


def install(
    endpoint: str = DEFAULT_ENDPOINT,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    protocol_version: str = DEFAULT_PROTOCOL_VERSION,
    raise_on_error: bool = False,
    patch_a2a_sdk: bool = False,
) -> SkeinClient:
    """Install (or replace) the process-wide Skein client.

    If `patch_a2a_sdk=True` and the `a2a-sdk` package is importable, monkey-patch
    its client/server entry points to auto-capture. Returns the active client.
    """
    global _client
    with _client_lock:
        _client = SkeinClient(
            endpoint,
            timeout=timeout,
            protocol_version=protocol_version,
            raise_on_error=raise_on_error,
        )
    if patch_a2a_sdk:
        try:
            from . import a2a_patch
            a2a_patch.install(_client)
        except Exception as e:
            log.warning("a2a-sdk monkey-patch failed (a2a-sdk may not be installed): %s", e)
    return _client


def get_client() -> SkeinClient:
    """Return the current client, creating a default one if `install()` not called."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = SkeinClient()
    return _client


def send(payload: dict[str, Any], **kwargs) -> dict[str, Any] | None:
    return get_client().send(payload, **kwargs)


def send_agent_card(card: dict[str, Any]) -> dict[str, Any] | None:
    return get_client().send_agent_card(card)
