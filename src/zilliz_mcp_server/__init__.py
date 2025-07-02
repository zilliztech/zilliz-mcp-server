"""
Zilliz MCP Server - Core module

A Model Context Protocol (MCP) server implementation for Zilliz Cloud and Milvus.
"""

from .settings import config, get_config, ZillizConfig

__all__ = [
    "config",
    "get_config", 
    "ZillizConfig",
] 