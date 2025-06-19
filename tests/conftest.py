"""
Pytest configuration and common fixtures for Zilliz MCP Server tests.
"""

import os
import pytest
from unittest.mock import Mock, patch
from typing import Dict, Any


@pytest.fixture
def mock_env_vars():
    """Mock environment variables for testing."""
    return {
        "ZILLIZ_CLOUD_TOKEN": "test-token-123",
        "ZILLIZ_CLOUD_URI": "https://test.api.zilliz.com",
        "ZILLIZ_CLOUD_FREE_CLUSTER_REGION": "test-region",
        "MCP_SERVER_PORT": "8080",
        "MCP_SERVER_HOST": "test-host"
    }


@pytest.fixture
def mock_empty_env_vars():
    """Mock empty environment variables for testing error cases."""
    return {
        "ZILLIZ_CLOUD_TOKEN": "",
        "ZILLIZ_CLOUD_URI": "",
        "ZILLIZ_CLOUD_FREE_CLUSTER_REGION": "",
        "MCP_SERVER_PORT": "",
        "MCP_SERVER_HOST": ""
    }


@pytest.fixture
def sample_project_response():
    """Sample project API response for testing."""
    return {
        "code": 0,
        "data": [
            {
                "projectName": "Test Project",
                "projectId": "proj-test123",
                "instanceCount": 2,
                "createTime": "2023-06-14T06:59:07Z"
            }
        ]
    }


@pytest.fixture
def sample_cluster_response():
    """Sample cluster API response for testing."""
    return {
        "code": 0,
        "data": {
            "clusters": [
                {
                    "clusterId": "in01-test123",
                    "clusterName": "test-cluster",
                    "description": "Test cluster",
                    "regionId": "gcp-us-west1",
                    "plan": "Free",
                    "cuType": "",
                    "cuSize": 0,
                    "status": "RUNNING",
                    "connectAddress": "https://test.api.zilliz.com:19530",
                    "privateLinkAddress": "",
                    "projectId": "proj-test123",
                    "createTime": "2023-06-14T07:00:00Z"
                }
            ]
        }
    }


@pytest.fixture
def sample_error_response():
    """Sample error API response for testing."""
    return {
        "code": 1001,
        "message": "Test error message"
    }


@pytest.fixture
def mock_requests_get():
    """Mock requests.get for HTTP client testing."""
    with patch('requests.get') as mock_get:
        yield mock_get


@pytest.fixture
def mock_requests_post():
    """Mock requests.post for HTTP client testing."""
    with patch('requests.post') as mock_post:
        yield mock_post


@pytest.fixture
def mock_requests_delete():
    """Mock requests.delete for HTTP client testing."""
    with patch('requests.delete') as mock_delete:
        yield mock_delete


@pytest.fixture
def mock_response():
    """Create a mock response object."""
    response = Mock()
    response.raise_for_status.return_value = None
    response.content = b'{"code": 0, "data": {}}'
    response.json.return_value = {"code": 0, "data": {}}
    return response 