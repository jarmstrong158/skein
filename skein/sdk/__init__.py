"""Skein client SDK.

Two ways to use it:

  1. Explicit (always works):
        import skein
        skein.install(endpoint="http://localhost:5050")
        skein.send(payload, direction="outbound")          # for each A2A message
        skein.send_agent_card(card)                        # once per agent identity

  2. Auto-capture (if `a2a-sdk` is installed):
        import skein
        skein.install(endpoint="http://localhost:5050", patch_a2a_sdk=True)
        # ...then your existing a2a-sdk code captures automatically.
"""

from .client import (
    SkeinClient,
    install,
    send,
    send_agent_card,
    get_client,
)

__all__ = ["SkeinClient", "install", "send", "send_agent_card", "get_client"]
