import asyncio

from zilliz_mcp_server.app import zilliz_mcp
from zilliz_mcp_server.tools.zilliz import zilliz_tools
from zilliz_mcp_server.tools.milvus import milvus_tools


def main():
    """Main entry point for the MCP server."""
    print("🚀 Starting MCP server...")
    try:
        asyncio.run(zilliz_mcp.run(transport='stdio'))
    except Exception as e:
        print(f"❌ MCP server failed: {e}")


if __name__ == "__main__":
    main()