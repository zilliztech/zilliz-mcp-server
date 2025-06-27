from mcp.server.fastmcp import FastMCP
from zilliz_mcp_server.settings import config

# Initialize MCP server with configuration
zilliz_mcp = FastMCP("zilliz-mcp-server", port=config.mcp_server_port, host=config.mcp_server_host, stateless_http=True)