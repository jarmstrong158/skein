"""Tests for the internal Skein client helper.

Note: `skein.sdk` is internal in v1 (used by `skein demo`); these tests
exist to prevent regressions in the helper, not to certify a public API.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from skein.sdk import client as sdk_client
from skein.sdk import SkeinClient


class _RecordingHandler(BaseHTTPRequestHandler):
    """Records every POST in handler.server.calls."""
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.calls.append((self.path, body))
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *_a, **_k):  # silence
        pass


@pytest.fixture
def recording_server():
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    server.calls = []  # type: ignore[attr-defined]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server
    server.shutdown()
    server.server_close()


def _endpoint(server):
    return f"http://127.0.0.1:{server.server_address[1]}"


def test_explicit_send_posts_to_ingest(recording_server):
    client = SkeinClient(_endpoint(recording_server))
    client.send({"jsonrpc": "2.0", "id": 1, "method": "x", "params": {}}, direction="outbound")
    assert len(recording_server.calls) == 1
    path, _ = recording_server.calls[0]
    assert path == "/trace/ingest"


def test_send_agent_card_posts_to_agent_card(recording_server):
    client = SkeinClient(_endpoint(recording_server))
    client.send_agent_card({"name": "x", "url": "http://a"})
    assert recording_server.calls[0][0] == "/trace/agent_card"


def test_install_sets_module_level_client_and_send_works(recording_server):
    sdk_client.install(_endpoint(recording_server))
    sdk_client.send({"jsonrpc": "2.0", "id": 1, "method": "x", "params": {}}, direction="outbound")
    assert len(recording_server.calls) == 1


def test_unreachable_endpoint_does_not_raise_by_default():
    # No server here — must swallow.
    client = SkeinClient("http://127.0.0.1:1", timeout=0.1)
    assert client.send({"jsonrpc": "2.0", "id": 1, "method": "x"}) is None


def test_unreachable_endpoint_raises_when_configured():
    client = SkeinClient("http://127.0.0.1:1", timeout=0.1, raise_on_error=True)
    with pytest.raises(Exception):
        client.send({"jsonrpc": "2.0", "id": 1, "method": "x"})
