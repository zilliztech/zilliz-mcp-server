"""Milvus Data Plane tools."""
from typing import Dict, Any, List, Optional
from zilliz_mcp_server.common import openapi_client
from zilliz_mcp_server.settings import config
from zilliz_mcp_server.app import zilliz_mcp


@zilliz_mcp.tool()
async def list_databases(cluster_id: str, region_id: str) -> List[str]:
    """
    List all databases in the current cluster.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
    Returns:
        List of database names
        Example:
        [
            "default",
            "test"
        ]
        
    """
    try:
        # Build request body (empty for list databases)
        body = {}
        
        response = openapi_client.data_plane_api_request(
            uri="/v2/vectordb/databases/list",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Extract database names from response
        databases = response.get('data', [])
        
        return databases
        
    except Exception as e:
        raise Exception(f"Failed to list databases: {str(e)}") from e


@zilliz_mcp.tool()
async def list_collections(cluster_id: str, region_id: str, db_name: str = "default") -> List[str]:
    """
    List all collection names in the specified database.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        db_name: The name of an existing database (default: "default")
    Returns:
        List of collection names
        Example:
        [
            "quick_setup_new",
            "customized_setup_1", 
            "customized_setup_2"
        ]
        
    """
    try:
        # Build request body with database name
        body = {
            "dbName": db_name
        }
        
        response = openapi_client.data_plane_api_request(
            uri="/v2/vectordb/collections/list",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Extract collection names from response
        collections = response.get('data', [])
        
        return collections
        
    except Exception as e:
        raise Exception(f"Failed to list collections: {str(e)}") from e


@zilliz_mcp.tool()
async def create_collection(
    cluster_id: str, 
    region_id: str, 
    collection_name: str, 
    dimension: int,
    db_name: str = "default",
    metric_type: str = "L2",
    id_type: str = "Int64",
    auto_id: bool = True,
    primary_field_name: str = "id",
    vector_field_name: str = "vector"
) -> Dict[str, Any]:
    """
    Create a collection in a specified cluster using Quick Setup.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        collection_name: The name of the collection to create
        dimension: The number of dimensions a vector value should have
        db_name: The name of the database (default: "default")
        metric_type: The metric type (default: "L2", options: "L2", "IP", "COSINE")
        id_type: The data type of the primary field (default: "Int64", options: "Int64", "VarChar")
        auto_id: Whether the primary field automatically increments (default: True)
        primary_field_name: The name of the primary field (default: "id")
        vector_field_name: The name of the vector field (default: "vector")
    Returns:
        Dict containing the response
        Example:
        {
            "code": 0,
            "data": {}
        }
        
    """
    try:
        # Build request body for Quick Setup
        body = {
            "dbName": db_name,
            "collectionName": collection_name,
            "dimension": dimension,
            "metricType": metric_type,
            "idType": id_type,
            "autoID": auto_id,
            "primaryFieldName": primary_field_name,
            "vectorFieldName": vector_field_name
        }
        
        # Add max_length parameter if using VarChar for primary key
        if id_type == "VarChar":
            body["params"] = {
                "max_length": 255
            }
        
        response = openapi_client.data_plane_api_request(
            uri="/v2/vectordb/collections/create",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        return response
        
    except Exception as e:
        raise Exception(f"Failed to create collection: {str(e)}") from e


