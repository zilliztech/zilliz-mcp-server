"""Zilliz Control Plane tools."""

from typing import Dict, Any, List
from zilliz_mcp_server.common import openapi_client
from zilliz_mcp_server.settings import config


async def get_projects_info() -> List[Dict[str, Any]]:
    """
    Get formatted project information.
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


async def list_clusters(page_size: int = 10, current_page: int = 1) -> List[Dict[str, Any]]:
    """
    List all clusters scoped to API Key.
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


async def create_free_cluster(cluster_name: str, project_id: str) -> Dict[str, Any]:
    """
    Create a free cluster.
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




