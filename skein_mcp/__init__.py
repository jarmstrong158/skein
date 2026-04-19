"""skein_mcp — MCP server exposing Skein trace data to Claude.

Separate process (stdio transport), separate package, separate install path.
The main `skein` package does not depend on this; this package depends on
`skein` for the underlying queries and `mcp` for the protocol.
"""
