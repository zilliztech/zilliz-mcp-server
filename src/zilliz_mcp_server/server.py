import asyncio
from typing import Any, Dict, List
from mcp.server.fastmcp import FastMCP
from zilliz_mcp_server.tools.zilliz import zilliz_tools


# Initialize MCP server
mcp = FastMCP("zilliz-mcp-server")

@mcp.tool()
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
    result = await zilliz_tools.get_projects_info()
    return result


@mcp.tool()
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
    result = await zilliz_tools.list_clusters(page_size=page_size, current_page=current_page)
    return result


@mcp.tool()
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
    result = await zilliz_tools.create_free_cluster(
        cluster_name=cluster_name,
        project_id=project_id,
    )
    return result


if __name__ == "__main__":
    print("🚀 Starting MCP server...")
    try:
        asyncio.run(mcp.run(transport='stdio'))
    except Exception as e:
        print(f"❌ MCP server failed: {e}")