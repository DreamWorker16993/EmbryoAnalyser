"""Initialize the Windows JVM on the main thread before serving MCP requests."""
import contextlib
import sys
from environment import configure
configure()
# Diagnostic output must never enter the JSON-RPC stdout channel.
with contextlib.redirect_stdout(sys.stderr):
    from fiji_mcp.bridge import get_ij
    get_ij()
from fiji_mcp.__main__ import main
main()
