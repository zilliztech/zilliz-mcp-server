"""Zilliz Control Plane tools."""

import json
import logging
from typing import Dict, Any, List, Optional, Union
from zilliz_mcp_server.common import openapi_client
from zilliz_mcp_server.settings import config
from zilliz_mcp_server.app import zilliz_mcp

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

@zilliz_mcp.tool()
async def list_projects() -> str:
    """
    List all projects scoped to API Key in Zilliz Cloud.
    
    Args:
        None
    Returns:
        JSON string containing the API response with projects data
        Example:
        '[{"project_name": "Default Project", "project_id": "proj-f5b02814db7ccfe2d16293", "instance_count": 0, "create_time": "2023-06-14T06:59:07Z"}]'
        
    """
    try:
        # Log request
        logger.info("LIST_PROJECTS: fetching all projects")
        
        response = openapi_client.control_plane_api_request("/v2/projects")
        projects = response.get('data', [])
        
        # Format project information
        formatted_projects = []
        for project in projects:
            project_info = {
                'project_name': project.get('projectName', 'Unknown'),
                'project_id': project.get('projectId', 'Unknown'),
                'instance_count': project.get('instanceCount', 0),
                'create_time': project.get('createTime', 'Unknown')
            }
            formatted_projects.append(project_info)
        
        # Log results
        logger.info(f"LIST_PROJECTS RESULT: found {len(formatted_projects)} projects")
        
        return json.dumps(formatted_projects)
        
    except Exception as e:
        logger.error(f"LIST_PROJECTS ERROR: {str(e)}")
        raise Exception(f"Failed to get projects info: {str(e)}") from e


@zilliz_mcp.tool()
async def list_clusters(page_size: int = 10, current_page: int = 1) -> str:
    """
    List all clusters scoped to API Key in Zilliz Cloud.
    If you want to list all clusters, you can set page_size to 100 and current_page to 1.
    
    Args:
        page_size: The number of records to include in each response (default: 10)
        current_page: The current page number (default: 1)
    Returns:
        List containing cluster data
        Example:
        [
            {
                "cluster_id": "inxx-xxxxxxxxxxxxxxx",
                "cluster_name": "dedicated-3",
                "description": "",
                "region_id": "aws-us-west-2",
                "plan": "Standard",
                "cu_type": "Performance-optimized",
                "cu_size": 1,
                "status": "RUNNING",
                "connect_address": "https://inxx-xxxxxxxxxxxxxxx.aws-us-west-2.vectordb.zillizcloud.com:19530",
                "private_link_address": "",
                "project_id": "proj-xxxxxxxxxxxxxxxxxxxxxx",
                "create_time": "2024-06-30T16:49:50Z"
            }
        ]
        
    """
    try:
        # Log request
        logger.info(f"LIST_CLUSTERS: page_size={page_size}, current_page={current_page}")
        
        # Build query parameters
        params = {
            'pageSize': page_size,
            'currentPage': current_page
        }
        
        response = openapi_client.control_plane_api_request("/v2/clusters", params_map=params)
        clusters_data = response.get('data', {})
        clusters = clusters_data.get('clusters', [])
        
        # Format cluster information
        formatted_clusters = []
        for cluster in clusters:
            cluster_info = {
                'cluster_id': cluster.get('clusterId', 'Unknown'),
                'cluster_name': cluster.get('clusterName', 'Unknown'),
                'description': cluster.get('description', ''),
                'region_id': cluster.get('regionId', 'Unknown'),
                'plan': cluster.get('plan', 'Unknown'),
                'cu_type': cluster.get('cuType', ''),
                'cu_size': cluster.get('cuSize', 0),
                'status': cluster.get('status', 'Unknown'),
                'connect_address': cluster.get('connectAddress', ''),
                'private_link_address': cluster.get('privateLinkAddress', ''),
                'project_id': cluster.get('projectId', 'Unknown'),
                'create_time': cluster.get('createTime', 'Unknown')
            }
            formatted_clusters.append(cluster_info)
        
        # Log results
        logger.info(f"LIST_CLUSTERS RESULT: found {len(formatted_clusters)} clusters")
        
        return json.dumps(formatted_clusters)
        
    except Exception as e:
        logger.error(f"LIST_CLUSTERS ERROR: {str(e)}")
        raise Exception(f"Failed to list clusters: {str(e)}") from e

@zilliz_mcp.tool()
async def create_free_cluster(cluster_name: str, project_id: str) -> str:
    """
    Create a free cluster in Zilliz Cloud.
    
    Args:
        cluster_name: Name of the cluster to create
        project_id: ID of the project to which the cluster belongs
    Returns:
        Dict containing cluster creation info
        Example:
        {
            "cluster_id": "inxx-xxxxxxxxxxxxxxx",
            "username": "db_xxxxxxxx",
            "prompt": "successfully submitted, cluster is being created..."
        }
        
    """
    try:
        # Log request
        logger.info(f"CREATE_FREE_CLUSTER: cluster_name={cluster_name}, project_id={project_id}")
        
        # Get free cluster region_id from config
        region_id = config.free_cluster_region
        
        # Build request body
        body = {
            'clusterName': cluster_name,
            'projectId': project_id,
            'regionId': region_id
        }
        
        response = openapi_client.control_plane_api_request(
            "/v2/clusters/createFree", 
            body_map=body, 
            method="POST"
        )
        
        # Extract and format the response data
        data = response.get('data', {})
        cluster_info = {
            'cluster_id': data.get('clusterId', 'Unknown'),
            'username': data.get('username', 'Unknown'),
            'prompt': data.get('prompt', 'Unknown'),
        }
        
        # Log results
        logger.info(f"CREATE_FREE_CLUSTER RESULT: cluster_id={cluster_info['cluster_id']}")
        
        return json.dumps(cluster_info)
        
    except Exception as e:
        logger.error(f"CREATE_FREE_CLUSTER ERROR: {str(e)}")
        raise Exception(f"Failed to create free cluster: {str(e)}") from e

@zilliz_mcp.tool()
async def describe_cluster(cluster_id: str) -> str:
    """
    Describe a cluster in detail.
    
    Args:
        cluster_id: ID of the cluster whose details are to return
    Returns:
        Dict containing detailed cluster information
        Example:
        {
            "cluster_id": "inxx-xxxxxxxxxxxxxxx",
            "cluster_name": "Free-01",
            "project_id": "proj-b44a39b0c51cf21791a841",
            "description": "",
            "region_id": "gcp-us-west1",
            "cu_type": "",
            "plan": "Free",
            "status": "RUNNING",
            "connect_address": "https://inxx-xxxxxxxxxxxxxxx.api.gcp-us-west1.zillizcloud.com",
            "private_link_address": "",
            "cu_size": 0,
            "storage_size": 0,
            "snapshot_number": 0,
            "create_progress": 100,
            "create_time": "2024-06-24T12:35:09Z"
        }
        
    """
    try:
        # Log request
        logger.info(f"DESCRIBE_CLUSTER: cluster_id={cluster_id}")
        
        # Build URI with cluster_id as path parameter
        uri = f"/v2/clusters/{cluster_id}"
        
        response = openapi_client.control_plane_api_request(uri, method="GET")
        
        # Extract and format the response data
        data = response.get('data', {})
        cluster_info = {
            'cluster_id': data.get('clusterId', 'Unknown'),
            'cluster_name': data.get('clusterName', 'Unknown'),
            'project_id': data.get('projectId', 'Unknown'),
            'description': data.get('description', ''),
            'region_id': data.get('regionId', 'Unknown'),
            'cu_type': data.get('cuType', ''),
            'plan': data.get('plan', 'Unknown'),
            'status': data.get('status', 'Unknown'),
            'connect_address': data.get('connectAddress', ''),
            'private_link_address': data.get('privateLinkAddress', ''),
            'cu_size': data.get('cuSize', 0),
            'storage_size': data.get('storageSize', 0),
            'snapshot_number': data.get('snapshotNumber', 0),
            'create_progress': data.get('createProgress', 0),
            'create_time': data.get('createTime', 'Unknown')
        }
        
        # Log results
        logger.info(f"DESCRIBE_CLUSTER RESULT: name={cluster_info['cluster_name']}, status={cluster_info['status']}")
        
        return json.dumps(cluster_info)
        
    except Exception as e:
        logger.error(f"DESCRIBE_CLUSTER ERROR: {str(e)}")
        raise Exception(f"Failed to describe cluster: {str(e)}") from e

@zilliz_mcp.tool()
async def suspend_cluster(cluster_id: str) -> str:
    """
    Suspend a dedicated cluster in Zilliz Cloud.
    
    Args:
        cluster_id: ID of the cluster to suspend
    Returns:
        Dict containing cluster suspension info
        Example:
        {
            "cluster_id": "inxx-xxxxxxxxxxxxxxx",
            "prompt": "Successfully Submitted. The cluster will not incur any computing costs when suspended. You will only be billed for the storage costs during this time."
        }
        
    """
    try:
        # Log request
        logger.info(f"SUSPEND_CLUSTER: cluster_id={cluster_id}")
        
        # Build URI with cluster_id as path parameter
        uri = f"/v2/clusters/{cluster_id}/suspend"
        
        response = openapi_client.control_plane_api_request(uri, method="POST")
        
        # Extract and format the response data
        data = response.get('data', {})
        cluster_info = {
            'cluster_id': data.get('clusterId', cluster_id),
            'prompt': data.get('prompt', 'Cluster suspension request submitted')
        }
        
        # Log results
        logger.info(f"SUSPEND_CLUSTER RESULT: cluster_id={cluster_info['cluster_id']}")
        
        return json.dumps(cluster_info)
        
    except Exception as e:
        logger.error(f"SUSPEND_CLUSTER ERROR: {str(e)}")
        raise Exception(f"Failed to suspend cluster: {str(e)}") from e

@zilliz_mcp.tool()
async def resume_cluster(cluster_id: str) -> str:
    """
    Resume a dedicated cluster in Zilliz Cloud.
    
    Args:
        cluster_id: ID of the cluster to resume
    Returns:
        Dict containing cluster resumption info
        Example:
        {
            "cluster_id": "inxx-xxxxxxxxxxxxxxx",
            "prompt": "successfully Submitted. Cluster is being resumed, which is expected to takes several minutes. You can access data about the creation progress and status of your cluster by DescribeCluster API. Once the cluster status is RUNNING, you may access your vector database using the SDK."
        }
        
    """
    try:
        # Log request
        logger.info(f"RESUME_CLUSTER: cluster_id={cluster_id}")
        
        # Build URI with cluster_id as path parameter
        uri = f"/v2/clusters/{cluster_id}/resume"
        
        response = openapi_client.control_plane_api_request(uri, method="POST")
        
        # Extract and format the response data
        data = response.get('data', {})
        cluster_info = {
            'cluster_id': data.get('clusterId', cluster_id),
            'prompt': data.get('prompt', 'Cluster resumption request submitted')
        }
        
        # Log results
        logger.info(f"RESUME_CLUSTER RESULT: cluster_id={cluster_info['cluster_id']}")
        
        return json.dumps(cluster_info)
        
    except Exception as e:
        logger.error(f"RESUME_CLUSTER ERROR: {str(e)}")
        raise Exception(f"Failed to resume cluster: {str(e)}") from e

@zilliz_mcp.tool()
async def query_cluster_metrics(
    cluster_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    period: Optional[str] = None,
    granularity: str = "PT30S",
    metric_queries: List[Dict[str, str]] = []
) -> str:
    """
    Query the metrics of a specific cluster.
    
    Args:
        cluster_id: ID of the target cluster
        start: Starting date and time in ISO 8601 timestamp format (optional, use with end)
        end: Ending date and time in ISO 8601 timestamp format (optional, use with start)
        period: Duration in ISO 8601 duration format (optional, use when start/end not set)
        granularity: Time interval for metrics reporting in ISO 8601 duration format (minimum PT30S)
        metric_queries: List of metric queries, each containing 'metricName' and 'stat' fields
            - metricName: Name of the metric. Available options:
                * CU_COMPUTATION - Compute unit computation usage
                * CU_CAPACITY - Compute unit capacity
                * STORAGE_USE - Storage usage
                * REQ_INSERT_COUNT - Insert request count
                * REQ_BULK_INSERT_COUNT - Bulk insert request count
                * REQ_UPSERT_COUNT - Upsert request count
                * REQ_DELETE_COUNT - Delete request count
                * REQ_SEARCH_COUNT - Search request count
                * REQ_QUERY_COUNT - Query request count
                * VECTOR_REQ_INSERT_COUNT - Vector insert request count
                * VECTOR_REQ_UPSERT_COUNT - Vector upsert request count
                * VECTOR_REQ_SEARCH_COUNT - Vector search request count
                * REQ_INSERT_LATENCY_P99 - Insert request latency P99
                * REQ_BULK_INSERT_LATENCY_P99 - Bulk insert request latency P99
                * REQ_UPSERT_LATENCY_P99 - Upsert request latency P99
                * REQ_DELETE_LATENCY_P99 - Delete request latency P99
                * REQ_SEARCH_LATENCY_P99 - Search request latency P99
                * REQ_QUERY_LATENCY_P99 - Query request latency P99
                * REQ_SUCCESS_RATE - Request success rate
                * REQ_FAIL_RATE - Request failure rate
                * REQ_FAIL_RATE_INSERT - Insert request failure rate
                * REQ_FAIL_RATE_BULK_INSERT - Bulk insert request failure rate
                * REQ_FAIL_RATE_UPSERT - Upsert request failure rate
                * REQ_FAIL_RATE_DELETE - Delete request failure rate
                * REQ_FAIL_RATE_SEARCH - Search request failure rate
                * REQ_FAIL_RATE_QUERY - Query request failure rate
                * ENTITIES_LOADED - Number of loaded entities
                * ENTITIES_INSERT_RATE - Entity insert rate
                * COLLECTIONS_COUNT - Collection count
                * ENTITIES_COUNT - Total entity count
            - stat: Statistical method (AVG for average, P99 for 99th percentile - P99 only valid for latency metrics)
    Returns:
        Dict containing cluster metrics data
        Example:
        {
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
        
    """
    try:
        # Log request
        logger.info(f"QUERY_CLUSTER_METRICS: cluster_id={cluster_id}, metrics_count={len(metric_queries)}")
        
        # Build URI with cluster_id as path parameter
        uri = f"/v2/clusters/{cluster_id}/metrics/query"
        
        # Build request body
        body = {
            'granularity': granularity,
            'metricQueries': []
        }
        
        # Add time parameters (either start/end or period)
        if start and end:
            body['start'] = start
            body['end'] = end
        elif period:
            body['period'] = period
        else:
            raise ValueError("Either provide both 'start' and 'end', or provide 'period'")
        
        # Format metric queries
        for metric_query in metric_queries:
            if 'metricName' not in metric_query or 'stat' not in metric_query:
                raise ValueError("Each metric query must contain 'metricName' and 'stat' fields")
            
            formatted_query = {
                'name': metric_query['metricName'],
                'stat': metric_query['stat']
            }
            body['metricQueries'].append(formatted_query)
        
        response = openapi_client.control_plane_api_request(uri, body_map=body, method="POST")
        
        # Log results
        data = response.get('data', {})
        results = data.get('results', [])
        logger.info(f"QUERY_CLUSTER_METRICS RESULT: returned {len(results)} metric results")
        
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"QUERY_CLUSTER_METRICS ERROR: {str(e)}")
        raise Exception(f"Failed to query cluster metrics: {str(e)}") from e




