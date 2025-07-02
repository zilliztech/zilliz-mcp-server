"""
Unit tests for zilliz_mcp_server.settings module.

Tests configuration loading, validation, and error handling.
"""

import os
import pytest
from unittest.mock import patch, Mock
from zilliz_mcp_server.settings import ZillizConfig, get_config


class TestZillizConfig:
    """Test cases for ZillizConfig class."""

    def test_init_with_valid_env_vars(self, mock_env_vars):
        """Test successful initialization with valid environment variables."""
        with patch.dict(os.environ, mock_env_vars, clear=True):
            config = ZillizConfig()
            
            assert config.cloud_uri == "https://test.api.zilliz.com"
            assert config.token == "test-token-123"
            assert config.free_cluster_region == "test-region"
            assert config.mcp_server_port == 8080
            assert config.mcp_server_host == "test-host"

    def test_init_with_default_values(self):
        """Test initialization with default values when optional env vars are missing."""
        minimal_env = {"ZILLIZ_CLOUD_TOKEN": "test-token"}
        
        with patch.dict(os.environ, minimal_env, clear=True):
            config = ZillizConfig()
            
            assert config.cloud_uri == "https://api.cloud.zilliz.com"  # default
            assert config.token == "test-token"
            assert config.free_cluster_region == "gcp-us-west1"  # default
            assert config.mcp_server_port == 8000  # default
            assert config.mcp_server_host == "localhost"  # default

    def test_init_missing_required_token(self):
        """Test initialization fails when required token is missing."""
        env_vars = {"ZILLIZ_CLOUD_TOKEN": ""}  # Only token is empty
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="ZILLIZ_CLOUD_TOKEN is required"):
                ZillizConfig()

    def test_init_empty_token(self):
        """Test initialization fails when token is empty string."""
        env_vars = {"ZILLIZ_CLOUD_TOKEN": "   "}  # whitespace only
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="ZILLIZ_CLOUD_TOKEN is required"):
                ZillizConfig()

    def test_invalid_cloud_uri_format(self):
        """Test validation fails for invalid URI format."""
        env_vars = {
            "ZILLIZ_CLOUD_TOKEN": "test-token",
            "ZILLIZ_CLOUD_URI": "invalid-url"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="ZILLIZ_CLOUD_URI must be a valid URL"):
                ZillizConfig()

    def test_valid_uri_formats(self):
        """Test various valid URI formats are accepted."""
        valid_uris = [
            "https://api.zilliz.com",
            "http://localhost:8080",
            "https://test.api.zilliz.com:443/v1"
        ]
        
        for uri in valid_uris:
            env_vars = {
                "ZILLIZ_CLOUD_TOKEN": "test-token",
                "ZILLIZ_CLOUD_URI": uri
            }
            
            with patch.dict(os.environ, env_vars, clear=True):
                config = ZillizConfig()
                assert config.cloud_uri == uri

    def test_invalid_port_range(self):
        """Test validation fails for invalid port numbers."""
        invalid_ports = ["0", "65536", "99999", "-1"]
        
        for port in invalid_ports:
            env_vars = {
                "ZILLIZ_CLOUD_TOKEN": "test-token",
                "MCP_SERVER_PORT": port
            }
            
            with patch.dict(os.environ, env_vars, clear=True):
                with pytest.raises(ValueError, match="MCP_SERVER_PORT must be between 1 and 65535"):
                    ZillizConfig()

    def test_valid_port_range(self):
        """Test valid port numbers are accepted."""
        valid_ports = ["1", "8080", "65535"]
        
        for port in valid_ports:
            env_vars = {
                "ZILLIZ_CLOUD_TOKEN": "test-token",
                "MCP_SERVER_PORT": port
            }
            
            with patch.dict(os.environ, env_vars, clear=True):
                config = ZillizConfig()
                assert config.mcp_server_port == int(port)

    def test_invalid_port_format(self):
        """Test validation fails for non-numeric port values."""
        env_vars = {
            "ZILLIZ_CLOUD_TOKEN": "test-token",
            "MCP_SERVER_PORT": "not-a-number"
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError, match="MCP_SERVER_PORT must be a valid integer"):
                ZillizConfig()

    def test_empty_cloud_uri_uses_default(self):
        """Test empty cloud URI falls back to default."""
        env_vars = {
            "ZILLIZ_CLOUD_TOKEN": "test-token"
            # ZILLIZ_CLOUD_URI is not set, so it should use default
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            config = ZillizConfig()
            assert config.cloud_uri == "https://api.cloud.zilliz.com"


class TestGetConfig:
    """Test cases for get_config function."""

    def test_get_config_returns_global_instance(self, mock_env_vars):
        """Test get_config returns the global config instance."""
        with patch.dict(os.environ, mock_env_vars, clear=True):
            # Import here to ensure fresh config instance
            from zilliz_mcp_server.settings import config as global_config
            
            retrieved_config = get_config()
            assert retrieved_config is global_config
            assert isinstance(retrieved_config, ZillizConfig)

    def test_config_singleton_behavior(self, mock_env_vars):
        """Test that multiple calls to get_config return the same instance."""
        with patch.dict(os.environ, mock_env_vars, clear=True):
            config1 = get_config()
            config2 = get_config()
            assert config1 is config2 