"""
Unit tests for zilliz_mcp_server.common.openapi_client module.

Tests HTTP client functionality, error handling, and response parsing.
"""

import json
import pytest
import responses
from unittest.mock import patch, Mock
from requests.exceptions import HTTPError, RequestException
from zilliz_mcp_server.common import openapi_client


class TestPrivateHelperFunctions:
    """Test cases for private helper functions."""

    def test_get_headers_with_token(self, mock_env_vars):
        """Test header generation with token."""
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.token = "test-token-123"
            headers = openapi_client._get_headers()
            
            expected_headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "X-MCP-TRACE": "true",
                "Authorization": "Bearer test-token-123"
            }
            assert headers == expected_headers

    def test_get_headers_without_token(self):
        """Test header generation without token."""
        env_vars = {"ZILLIZ_CLOUD_TOKEN": ""}
        with patch.dict('os.environ', env_vars, clear=True):
            # Force reload of config
            with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
                mock_config.token = ""
                headers = openapi_client._get_headers()
                
                expected_headers = {
                    "accept": "application/json", 
                    "content-type": "application/json",
                    "X-MCP-TRACE": "true"
                }
                assert headers == expected_headers

    def test_parse_response_success(self):
        """Test successful response parsing."""
        mock_response = Mock()
        mock_response.content = b'{"code": 0, "data": {"test": "value"}}'
        mock_response.json.return_value = {"code": 0, "data": {"test": "value"}}
        
        result = openapi_client._parse_response(mock_response)
        assert result == {"code": 0, "data": {"test": "value"}}

    def test_parse_response_empty_content(self):
        """Test parsing response with empty content."""
        mock_response = Mock()
        mock_response.content = b''
        
        result = openapi_client._parse_response(mock_response)
        assert result == {}

    def test_parse_response_invalid_json(self):
        """Test parsing response with invalid JSON."""
        mock_response = Mock()
        mock_response.content = b'invalid json'
        mock_response.json.side_effect = ValueError("Invalid JSON")
        
        with pytest.raises(Exception, match="Failed to parse response as JSON"):
            openapi_client._parse_response(mock_response)

    def test_parse_response_business_error(self):
        """Test parsing response with business error code."""
        mock_response = Mock()
        mock_response.content = b'{"code": 1001, "message": "Business error"}'
        mock_response.json.return_value = {"code": 1001, "message": "Business error"}
        
        with pytest.raises(Exception, match="Business error: Business error"):
            openapi_client._parse_response(mock_response)

    def test_parse_response_business_error_no_message(self):
        """Test parsing response with business error but no message."""
        mock_response = Mock()
        mock_response.content = b'{"code": 1001}'
        mock_response.json.return_value = {"code": 1001}
        
        with pytest.raises(Exception, match="Business error: Unknown business error"):
            openapi_client._parse_response(mock_response)


class TestHttpMethods:
    """Test cases for HTTP method functions."""

    @responses.activate
    def test_get_success(self):
        """Test successful GET request."""
        responses.add(
            responses.GET,
            "https://test.api.com/test",
            json={"code": 0, "data": "success"},
            status=200
        )
        
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.token = "test-token"
            result = openapi_client.get("https://test.api.com/test")
            
        assert result == {"code": 0, "data": "success"}

    @responses.activate
    def test_get_with_params(self):
        """Test GET request with query parameters."""
        responses.add(
            responses.GET,
            "https://test.api.com/test",
            json={"code": 0, "data": "success"},
            status=200
        )
        
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.token = "test-token"
            result = openapi_client.get("https://test.api.com/test", {"param1": "value1"})
            
        assert result == {"code": 0, "data": "success"}
        # Check that parameters were included in the request
        assert len(responses.calls) == 1
        assert "param1=value1" in responses.calls[0].request.url

    @responses.activate
    def test_get_http_error(self):
        """Test GET request with HTTP error."""
        responses.add(
            responses.GET,
            "https://test.api.com/test",
            status=404
        )
        
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.token = "test-token"
            with pytest.raises(HTTPError):
                openapi_client.get("https://test.api.com/test")

    @responses.activate
    def test_post_success(self):
        """Test successful POST request."""
        responses.add(
            responses.POST,
            "https://test.api.com/test",
            json={"code": 0, "data": "created"},
            status=201
        )
        
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.token = "test-token"
            body = {"name": "test"}
            result = openapi_client.post("https://test.api.com/test", body_map=body)
            
        assert result == {"code": 0, "data": "created"}

    @responses.activate
    def test_post_with_params_and_body(self):
        """Test POST request with both query params and body."""
        responses.add(
            responses.POST,
            "https://test.api.com/test",
            json={"code": 0, "data": "created"},
            status=201
        )
        
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.token = "test-token"
            params = {"version": "v2"}
            body = {"name": "test"}
            result = openapi_client.post("https://test.api.com/test", params, body)
            
        assert result == {"code": 0, "data": "created"}
        assert len(responses.calls) == 1
        assert "version=v2" in responses.calls[0].request.url

    @responses.activate
    def test_delete_success(self):
        """Test successful DELETE request."""
        responses.add(
            responses.DELETE,
            "https://test.api.com/test",
            json={"code": 0, "data": "deleted"},
            status=200
        )
        
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.token = "test-token"
            result = openapi_client.delete("https://test.api.com/test")
            
        assert result == {"code": 0, "data": "deleted"}


class TestControlPlaneApiRequest:
    """Test cases for control_plane_api_request function."""

    def test_empty_uri_raises_error(self):
        """Test that empty URI raises ValueError."""
        with pytest.raises(ValueError, match="uri is required and cannot be empty"):
            openapi_client.control_plane_api_request("")

    def test_whitespace_uri_raises_error(self):
        """Test that whitespace-only URI raises ValueError."""
        with pytest.raises(ValueError, match="uri is required and cannot be empty"):
            openapi_client.control_plane_api_request("   ")

    @responses.activate
    def test_get_request_url_construction(self):
        """Test proper URL construction for GET requests."""
        responses.add(
            responses.GET,
            "https://api.cloud.zilliz.com/v2/projects",
            json={"code": 0, "data": []},
            status=200
        )
        
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.cloud_uri = "https://api.cloud.zilliz.com"
            mock_config.token = "test-token"
            
            result = openapi_client.control_plane_api_request("/v2/projects")
            
        assert result == {"code": 0, "data": []}

    @responses.activate  
    def test_post_request_url_construction(self):
        """Test proper URL construction for POST requests."""
        responses.add(
            responses.POST,
            "https://api.cloud.zilliz.com/v2/clusters",
            json={"code": 0, "data": {"id": "test"}},
            status=201
        )
        
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.cloud_uri = "https://api.cloud.zilliz.com"
            mock_config.token = "test-token"
            
            body = {"name": "test-cluster"}
            result = openapi_client.control_plane_api_request("/v2/clusters", body_map=body, method="POST")
            
        assert result == {"code": 0, "data": {"id": "test"}}

    def test_unsupported_method_raises_error(self):
        """Test that unsupported HTTP method raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported method: PATCH"):
            openapi_client.control_plane_api_request("/v2/test", method="PATCH")


class TestDataPlaneApiRequest:
    """Test cases for data_plane_api_request function."""

    def test_empty_uri_raises_error(self):
        """Test that empty URI raises ValueError."""
        with pytest.raises(ValueError, match="uri is required and cannot be empty"):
            openapi_client.data_plane_api_request("", "", "cluster1", "region1")

    def test_empty_cluster_id_raises_error(self):
        """Test that empty cluster_id raises ValueError."""
        with pytest.raises(ValueError, match="cluster_id is required and cannot be empty"):
            openapi_client.data_plane_api_request("https://test.com", "/v2/test", "", "region1")

    def test_empty_region_id_raises_error(self):
        """Test that empty region_id raises ValueError."""
        with pytest.raises(ValueError, match="region_id is required and cannot be empty"):
            openapi_client.data_plane_api_request("https://test.com", "/v2/test", "cluster1", "")

    @responses.activate
    def test_data_plane_post_request(self):
        """Test successful data plane POST request."""
        responses.add(
            responses.POST,
            "https://test-endpoint.com/v2/vectordb/collections/list",
            json={"code": 0, "data": ["collection1", "collection2"]},
            status=200
        )
        
        with patch('zilliz_mcp_server.common.openapi_client.config') as mock_config:
            mock_config.token = "test-token"
            
            result = openapi_client.data_plane_api_request(
                endpoint="https://test-endpoint.com",
                uri="/v2/vectordb/collections/list",
                cluster_id="cluster1",
                region_id="region1",
                body_map={"dbName": "default"},
                method="POST"
            )
            
        assert result == {"code": 0, "data": ["collection1", "collection2"]}

    def test_unsupported_method_raises_error(self):
        """Test that unsupported HTTP method raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported method: PUT"):
            openapi_client.data_plane_api_request(
                "https://test.com", "/v2/test", "cluster1", "region1", method="PUT"
            ) 