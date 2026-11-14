"""Optional thin FastMCP adapter over the same public engine."""
from .engine import OBSERVATION, RULES, evaluate_action


def create_server():
    try:
        from fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("Install fastmcp>=4,<5 to enable the optional MCP adapter") from exc
    server = FastMCP("f1-pit-wall")
    server.tool(name="observe")(lambda: OBSERVATION)
    server.tool(name="rules")(lambda: RULES)
    server.tool(name="preview")(evaluate_action)
    return server
