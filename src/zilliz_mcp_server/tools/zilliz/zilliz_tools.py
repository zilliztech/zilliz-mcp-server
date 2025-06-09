"""Zilliz Control Plane tools."""

from typing import Dict, Any, List
from zilliz_mcp_server.common import openapi_client
from zilliz_mcp_server.settings import config
from zilliz_mcp_server.app import zilliz_mcp

@zilliz_mcp.tool()
async def list_projects() -> List[Dict[str, Any]]:
    """
    List all projects scoped to API Key in Zilliz Cloud.
    
    Args:
        None
    Returns:
        Dict containing the API response with projects data
        Example:
        [
            {
                "project_name": "Default Project",
                "project_id": "proj-f5b02814db7ccfe2d16293",
                "instance_count": 0,
                "create_time": "2023-06-14T06:59:07Z"
            }
        ]
        
    """
    try:
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
            
        return formatted_projects
        
    except Exception as e:
        raise Exception(f"Failed to get projects info: {str(e)}") from e


@zilliz_mcp.tool()
async def list_clusters(page_size: int = 10, current_page: int = 1) -> List[Dict[str, Any]]:
    """
    List all clusters scoped to API Key in Zilliz Cloud.
    
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
            
        return formatted_clusters
        
    except Exception as e:
        raise Exception(f"Failed to list clusters: {str(e)}") from e

@zilliz_mcp.tool()
async def create_free_cluster(cluster_name: str, project_id: str) -> Dict[str, Any]:
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
        
        return cluster_info
        
    except Exception as e:
        raise Exception(f"Failed to create free cluster: {str(e)}") from e

@zilliz_mcp.tool()
async def describe_cluster(cluster_id: str) -> Dict[str, Any]:
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
        
        return cluster_info
        
    except Exception as e:
        raise Exception(f"Failed to describe cluster: {str(e)}") from e




