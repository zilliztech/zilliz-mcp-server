"""
Unit tests for zilliz_mcp_server.tools.zilliz.zilliz_tools module.

Tests control plane operations like cluster and project management.
"""

import json
import pytest
from unittest.mock import patch, Mock, AsyncMock
import logging

# Enable asyncio for all async tests in this module
pytestmark = pytest.mark.asyncio


# Mock the MCP app to avoid import issues during testing
@pytest.fixture(autouse=True)
def mock_zilliz_mcp():
    """Mock the zilliz_mcp app for testing."""
    with patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.zilliz_mcp') as mock_app:
        mock_app.tool.return_value = lambda func: func  # Return function unchanged
        yield mock_app


class TestListProjects:
    """Test cases for list_projects function."""

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_list_projects_success(self, mock_client, sample_project_response):
        """Test successful project listing."""
        # Import function after mocking
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import list_projects
        
        mock_client.control_plane_api_request.return_value = sample_project_response
        
        result = await list_projects()
        result_data = json.loads(result)
        
        assert len(result_data) == 1
        assert result_data[0]['project_name'] == 'Test Project'
        assert result_data[0]['project_id'] == 'proj-test123'
        assert result_data[0]['instance_count'] == 2
        
        mock_client.control_plane_api_request.assert_called_once_with("/v2/projects")

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_list_projects_empty_response(self, mock_client):
        """Test project listing with empty response."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import list_projects
        
        mock_client.control_plane_api_request.return_value = {"code": 0, "data": []}
        
        result = await list_projects()
        result_data = json.loads(result)
        
        assert result_data == []

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_list_projects_api_error(self, mock_client):
        """Test project listing with API error."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import list_projects
        
        mock_client.control_plane_api_request.side_effect = Exception("API Error")
        
        with pytest.raises(Exception, match="Failed to get projects info: API Error"):
            await list_projects()

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_list_projects_missing_data_fields(self, mock_client):
        """Test project listing handles missing data fields gracefully."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import list_projects
        
        incomplete_response = {
            "code": 0,
            "data": [
                {
                    "projectName": "Test Project"
                    # Missing other fields
                }
            ]
        }
        mock_client.control_plane_api_request.return_value = incomplete_response
        
        result = await list_projects()
        result_data = json.loads(result)
        
        assert len(result_data) == 1
        assert result_data[0]['project_name'] == 'Test Project'
        assert result_data[0]['project_id'] == 'Unknown'  # Default value
        assert result_data[0]['instance_count'] == 0  # Default value


class TestListClusters:
    """Test cases for list_clusters function."""

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_list_clusters_success(self, mock_client, sample_cluster_response):
        """Test successful cluster listing."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import list_clusters
        
        mock_client.control_plane_api_request.return_value = sample_cluster_response
        
        result = await list_clusters(page_size=5, current_page=1)
        result_data = json.loads(result)
        
        assert len(result_data) == 1
        assert result_data[0]['cluster_id'] == 'in01-test123'
        assert result_data[0]['cluster_name'] == 'test-cluster'
        assert result_data[0]['status'] == 'RUNNING'
        
        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/clusters", 
            params_map={'pageSize': 5, 'currentPage': 1}
        )

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_list_clusters_default_params(self, mock_client, sample_cluster_response):
        """Test cluster listing with default parameters."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import list_clusters
        
        mock_client.control_plane_api_request.return_value = sample_cluster_response
        
        result = await list_clusters()
        
        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/clusters",
            params_map={'pageSize': 10, 'currentPage': 1}
        )


class TestCreateFreeCluster:
    """Test cases for create_free_cluster function."""

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.config')
    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_create_free_cluster_success(self, mock_client, mock_config):
        """Test successful free cluster creation."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import create_free_cluster
        
        mock_config.free_cluster_region = "gcp-us-west1"
        mock_client.control_plane_api_request.return_value = {
            "code": 0,
            "data": {
                "clusterId": "in01-test123",
                "username": "db_test123",
                "prompt": "successfully submitted"
            }
        }
        
        result = await create_free_cluster("test-cluster", "proj-test123")
        result_data = json.loads(result)
        
        assert result_data['cluster_id'] == 'in01-test123'
        assert result_data['username'] == 'db_test123'
        assert result_data['prompt'] == 'successfully submitted'
        
        expected_body = {
            'clusterName': 'test-cluster',
            'projectId': 'proj-test123',
            'regionId': 'gcp-us-west1'
        }
        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/clusters/createFree",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.config')
    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_create_free_cluster_api_error(self, mock_client, mock_config):
        """Test free cluster creation with API error."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import create_free_cluster
        
        mock_config.free_cluster_region = "gcp-us-west1"
        mock_client.control_plane_api_request.side_effect = Exception("Cluster creation failed")
        
        with pytest.raises(Exception, match="Failed to create free cluster: Cluster creation failed"):
            await create_free_cluster("test-cluster", "proj-test123")


class TestDescribeCluster:
    """Test cases for describe_cluster function."""

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_describe_cluster_success(self, mock_client):
        """Test successful cluster description."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import describe_cluster
        
        mock_response = {
            "code": 0,
            "data": {
                "clusterId": "in01-test123",
                "clusterName": "test-cluster",
                "status": "RUNNING",
                "connectAddress": "https://test.zilliz.com:19530"
            }
        }
        mock_client.control_plane_api_request.return_value = mock_response
        
        result = await describe_cluster("in01-test123")
        result_data = json.loads(result)
        
        assert result_data['cluster_id'] == 'in01-test123'
        assert result_data['cluster_name'] == 'test-cluster'
        assert result_data['status'] == 'RUNNING'
        assert result_data['connect_address'] == 'https://test.zilliz.com:19530'
        
        mock_client.control_plane_api_request.assert_called_once_with("/v2/clusters/in01-test123", method="GET")

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_describe_cluster_not_found(self, mock_client):
        """Test cluster description with cluster not found."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import describe_cluster
        
        mock_client.control_plane_api_request.side_effect = Exception("Cluster not found")
        
        with pytest.raises(Exception, match="Failed to describe cluster: Cluster not found"):
            await describe_cluster("nonexistent-cluster")


class TestSuspendCluster:
    """Test cases for suspend_cluster function."""

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_suspend_cluster_success(self, mock_client):
        """Test successful cluster suspension."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import suspend_cluster
        
        mock_response = {
            "code": 0,
            "data": {
                "clusterId": "in01-test123",
                "prompt": "Successfully submitted for suspension"
            }
        }
        mock_client.control_plane_api_request.return_value = mock_response
        
        result = await suspend_cluster("in01-test123")
        result_data = json.loads(result)
        
        assert result_data['cluster_id'] == 'in01-test123'
        assert 'suspension' in result_data['prompt']
        
        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/clusters/in01-test123/suspend",
            method="POST"
        )


class TestResumeCluster:
    """Test cases for resume_cluster function."""

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_resume_cluster_success(self, mock_client):
        """Test successful cluster resumption."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import resume_cluster
        
        mock_response = {
            "code": 0,
            "data": {
                "clusterId": "in01-test123",
                "prompt": "Successfully submitted for resumption"
            }
        }
        mock_client.control_plane_api_request.return_value = mock_response
        
        result = await resume_cluster("in01-test123")
        result_data = json.loads(result)
        
        assert result_data['cluster_id'] == 'in01-test123'
        assert 'resumption' in result_data['prompt']
        
        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/clusters/in01-test123/resume",
            method="POST"
        )


class TestQueryClusterMetrics:
    """Test cases for query_cluster_metrics function."""

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_query_cluster_metrics_with_start_end(self, mock_client):
        """Test successful cluster metrics query with start and end times."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        
        mock_response = {
            "code": 0,
            "data": {
                "results": [
                    {
                        "name": "CU_COMPUTATION",
                        "stat": "AVG",
                        "unit": "percent",
                        "values": [
                            {
                                "timestamp": "2024-06-30T16:09:53Z",
                                "value": "1.00"
                            }
                        ]
                    }
                ]
            }
        }
        mock_client.control_plane_api_request.return_value = mock_response
        
        metric_queries = [
            {"metricName": "CU_COMPUTATION", "stat": "AVG"}
        ]
        
        result = await query_cluster_metrics(
            cluster_id="in01-test123",
            start="2024-06-30T16:00:00Z",
            end="2024-06-30T17:00:00Z",
            granularity="PT1M",
            metric_queries=metric_queries
        )
        result_data = json.loads(result)
        
        assert result_data == mock_response
        expected_body = {
            "granularity": "PT1M",
            "start": "2024-06-30T16:00:00Z",
            "end": "2024-06-30T17:00:00Z",
            "metricQueries": [
                {"name": "CU_COMPUTATION", "stat": "AVG"}
            ]
        }
        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/clusters/in01-test123/metrics/query",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_query_cluster_metrics_with_period(self, mock_client):
        """Test successful cluster metrics query with period."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        
        mock_response = {
            "code": 0,
            "data": {
                "results": [
                    {
                        "name": "REQ_SEARCH_COUNT",
                        "stat": "AVG",
                        "unit": "count",
                        "values": [
                            {
                                "timestamp": "2024-06-30T16:09:53Z",
                                "value": "10"
                            }
                        ]
                    }
                ]
            }
        }
        mock_client.control_plane_api_request.return_value = mock_response
        
        metric_queries = [
            {"metricName": "REQ_SEARCH_COUNT", "stat": "AVG"}
        ]
        
        result = await query_cluster_metrics(
            cluster_id="in01-test123",
            period="PT1H",
            metric_queries=metric_queries
        )
        result_data = json.loads(result)
        
        assert result_data == mock_response
        expected_body = {
            "granularity": "PT30S",
            "period": "PT1H",
            "metricQueries": [
                {"name": "REQ_SEARCH_COUNT", "stat": "AVG"}
            ]
        }
        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/clusters/in01-test123/metrics/query",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_query_cluster_metrics_multiple_metrics(self, mock_client):
        """Test cluster metrics query with multiple metrics."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        
        mock_response = {
            "code": 0,
            "data": {
                "results": [
                    {
                        "name": "CU_COMPUTATION",
                        "stat": "AVG",
                        "unit": "percent",
                        "values": []
                    },
                    {
                        "name": "STORAGE_USE",
                        "stat": "AVG",
                        "unit": "bytes",
                        "values": []
                    }
                ]
            }
        }
        mock_client.control_plane_api_request.return_value = mock_response
        
        metric_queries = [
            {"metricName": "CU_COMPUTATION", "stat": "AVG"},
            {"metricName": "STORAGE_USE", "stat": "AVG"}
        ]
        
        result = await query_cluster_metrics(
            cluster_id="in01-test123",
            period="PT1H",
            metric_queries=metric_queries
        )
        result_data = json.loads(result)
        
        assert result_data == mock_response
        expected_body = {
            "granularity": "PT30S",
            "period": "PT1H",
            "metricQueries": [
                {"name": "CU_COMPUTATION", "stat": "AVG"},
                {"name": "STORAGE_USE", "stat": "AVG"}
            ]
        }
        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/clusters/in01-test123/metrics/query",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_query_cluster_metrics_no_time_params_error(self, mock_client):
        """Test cluster metrics query fails without time parameters."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        
        metric_queries = [
            {"metricName": "CU_COMPUTATION", "stat": "AVG"}
        ]
        
        with pytest.raises(Exception, match="Either provide both 'start' and 'end', or provide 'period'"):
            await query_cluster_metrics(
                cluster_id="in01-test123",
                metric_queries=metric_queries
            )

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_query_cluster_metrics_invalid_metric_query(self, mock_client):
        """Test cluster metrics query with invalid metric query format."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        
        metric_queries = [
            {"metricName": "CU_COMPUTATION"}  # Missing 'stat'
        ]
        
        with pytest.raises(Exception, match="Each metric query must contain 'metricName' and 'stat' fields"):
            await query_cluster_metrics(
                cluster_id="in01-test123",
                period="PT1H",
                metric_queries=metric_queries
            )

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_query_cluster_metrics_api_error(self, mock_client):
        """Test cluster metrics query with API error."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        
        mock_client.control_plane_api_request.side_effect = Exception("API Error")
        
        metric_queries = [
            {"metricName": "CU_COMPUTATION", "stat": "AVG"}
        ]
        
        with pytest.raises(Exception, match="Failed to query cluster metrics: API Error"):
            await query_cluster_metrics(
                cluster_id="in01-test123",
                period="PT1H",
                metric_queries=metric_queries
            )

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_query_cluster_metrics_empty_metric_queries(self, mock_client):
        """Test cluster metrics query with empty metric queries list."""
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        
        mock_response = {
            "code": 0,
            "data": {
                "results": []
            }
        }
        mock_client.control_plane_api_request.return_value = mock_response
        
        result = await query_cluster_metrics(
            cluster_id="in01-test123",
            period="PT1H",
            metric_queries=[]
        )
        result_data = json.loads(result)
        
        assert result_data == mock_response
        expected_body = {
            "granularity": "PT30S",
            "period": "PT1H",
            "metricQueries": []
        }
        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/clusters/in01-test123/metrics/query",
            body_map=expected_body,
            method="POST"
        ) 