import argparse

def main():
    """
    Main entry point for the zilliz-mcp-server script defined
    in pyproject.toml. It runs the MCP server with a specific transport
    protocol.
    """
    print("🚀 Starting Zilliz MCP server...")
    
    # Parse the command-line arguments to determine the transport protocol.
    parser = argparse.ArgumentParser(description="zilliz-mcp-server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol to use (default: stdio)"
    )
    args = parser.parse_args()

    try:
        # Import is done here to make sure environment variables are loaded
        # only after we make the changes.
        from zilliz_mcp_server.app import zilliz_mcp
        from zilliz_mcp_server.tools.zilliz import zilliz_tools
        from zilliz_mcp_server.tools.milvus import milvus_tools

        print(f"📡 Using transport: {args.transport}")
        zilliz_mcp.run(transport=args.transport)

    except Exception as e:
        print(f"❌ MCP server failed: {e}")


if __name__ == "__main__":
    main()