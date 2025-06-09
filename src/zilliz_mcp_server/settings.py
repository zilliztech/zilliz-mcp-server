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
    
    cloud_uri: str = os.getenv("ZILLIZ_CLOUD_URI", "https://api.cloud.zilliz.com/v2/clouds")
    cluster_endpoint: str = os.getenv("ZILLIZ_CLOUD_ClUSTER_ENDPOINT", "")
    token: str = os.getenv("ZILLIZ_CLOUD_TOKEN", "")


# Global config instance
config = ZillizConfig()


def get_config() -> ZillizConfig:
    """Get the Zilliz configuration."""
    return config

