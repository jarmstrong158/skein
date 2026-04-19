"""Skein — local-first observability for A2A multi-agent message flows."""

__version__ = "0.1.0"

from .sdk import SkeinClient, install, send, send_agent_card, get_client

__all__ = ["SkeinClient", "install", "send", "send_agent_card", "get_client", "__version__"]
