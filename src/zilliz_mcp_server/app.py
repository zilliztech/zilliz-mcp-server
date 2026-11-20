from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from zilliz_mcp_server.settings import config

# Initialize MCP server with configuration
zilliz_mcp = FastMCP("zilliz-mcp-server", port=config.mcp_server_port, host=config.mcp_server_host, stateless_http=True)

# Tool annotations let MCP clients tell reads from writes (e.g. to ask the user before a
# destructive call). They are hints for the client, not access control.
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


def read_tool():
    """Register a tool that only reads data."""
    return zilliz_mcp.tool(annotations=READ_ONLY)


def write_tool(*, destructive: bool, idempotent: bool = False):
    """Register a tool that changes resources or data.

    When ZILLIZ_MCP_READ_ONLY is set, the tool is not registered at all, so clients never
    see it. The function stays importable for tests.
    """
    annotations = ToolAnnotations(readOnlyHint=False, destructiveHint=destructive,
                                  idempotentHint=idempotent, openWorldHint=True)

    def decorator(fn):
        if config.read_only:
            return fn
        return zilliz_mcp.tool(annotations=annotations)(fn)

    return decorator
