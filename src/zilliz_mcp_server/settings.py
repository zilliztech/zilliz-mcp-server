"""
Configuration settings for Zilliz MCP Server.

Simple configuration module that loads Zilliz settings from .env file.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
# load_dotenv() automatically searches for .env file in current and parent directories
load_dotenv()


class ZillizConfig:
    """Zilliz Cloud configuration."""
    
    cloud_uri: str = os.getenv("ZILLIZ_CLOUD_URI", "https://api.cloud.zilliz.com")
    cluster_endpoint: str = os.getenv("ZILLIZ_CLOUD_CLUSTER_ENDPOINT", "")
    token: str = os.getenv("ZILLIZ_CLOUD_TOKEN", "")
    free_cluster_region: str = os.getenv("ZILLIZ_CLOUD_FREE_CLUSTER_REGION", "gcp-us-west1")
    
    # MCP Server configuration
    mcp_server_port: int = int(os.getenv("MCP_SERVER_PORT", "8000"))
    mcp_server_host: str = os.getenv("MCP_SERVER_HOST", "localhost")


# Global config instance
config = ZillizConfig()


def get_config() -> ZillizConfig:
    """Get the Zilliz configuration."""
    return config

