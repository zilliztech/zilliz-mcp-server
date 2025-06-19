"""Milvus Data Plane tools."""
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
async def list_databases(cluster_id: str, region_id: str, endpoint: str) -> str:
    """
    List all databases in the current cluster.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        endpoint: The cluster endpoint URL. Can be obtained by calling describe_cluster and using the connect_address field
    Returns:
        List of database names
        Example:
        [
            "default",
            "test"
        ]
        
    """
    try:
        # Log request
        logger.info(f"LIST_DATABASES: endpoint={endpoint}, cluster_id={cluster_id}")
        
        # Build request body (empty for list databases)
        body = {}
        
        response = openapi_client.data_plane_api_request(
            endpoint=endpoint,
            uri="/v2/vectordb/databases/list",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Extract database names from response
        databases = response.get('data', [])
        
        # Log results
        logger.info(f"LIST_DATABASES RESULT: {databases}")
        
        return json.dumps(databases)
        
    except Exception as e:
        logger.error(f"LIST_DATABASES ERROR: {str(e)}")
        raise Exception(f"Failed to list databases: {str(e)}") from e


@zilliz_mcp.tool()
async def list_collections(cluster_id: str, region_id: str, endpoint: str, db_name: str = "") -> str:
    """
    List all collection names in the specified database.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        endpoint: The cluster endpoint URL. Can be obtained by calling describe_cluster and using the connect_address field
        db_name: The name of an existing database. Pass explicit dbName or leave empty when cluster is free or serverless
    Returns:
        JSON string containing list of collection names
        Example:
        '["quick_setup_new", "customized_setup_1", "customized_setup_2"]'
        If no collections found, returns: '[]'
        
    """
    try:
        # Build request body with database name
        body = {}
        if db_name:
            body["dbName"] = db_name
        
        # Log request
        logger.info(f"LIST_COLLECTIONS: endpoint={endpoint}, cluster_id={cluster_id}, db_name={db_name}")
        
        response = openapi_client.data_plane_api_request(
            endpoint=endpoint,
            uri="/v2/vectordb/collections/list",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Extract collection names from response
        collections = response.get('data', [])
        
        # Serialize to JSON string
        collections_json = json.dumps(collections)
        
        # Log results
        logger.info(f"LIST_COLLECTIONS RESULT: {collections}")
        
        return collections_json
        
    except Exception as e:
        logger.error(f"LIST_COLLECTIONS ERROR: {str(e)}")
        raise Exception(f"Failed to list collections: {str(e)}") from e


@zilliz_mcp.tool()
async def create_collection(
    cluster_id: str, 
    region_id: str, 
    endpoint: str,
    collection_name: str, 
    dimension: int,
    db_name: str = "",
    metric_type: str = "COSINE",
    id_type: str = "Int64",
    auto_id: bool = True,
    primary_field_name: str = "id",
    vector_field_name: str = "vector"
) -> str:
    """
    Create a collection in a specified cluster using Quick Setup.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        endpoint: The cluster endpoint URL. Can be obtained by calling describe_cluster and using the connect_address field
        collection_name: The name of the collection to create
        dimension: The number of dimensions a vector value should have
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
        metric_type: The metric type (default: "COSINE", options: "L2", "IP", "COSINE") Ask the user to select the metric type, if user does not select, use default value "COSINE"
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
        # Log request
        logger.info(f"CREATE_COLLECTION: collection_name={collection_name}, dimension={dimension}, cluster_id={cluster_id}")
        
        # Build request body for Quick Setup
        body = {
            "collectionName": collection_name,
            "dimension": dimension,
            "metricType": metric_type,
            "idType": id_type,
            "autoID": auto_id,
            "primaryFieldName": primary_field_name,
            "vectorFieldName": vector_field_name
        }
        
        # Add dbName only if provided
        if db_name:
            body["dbName"] = db_name
        
        # Add max_length parameter if using VarChar for primary key
        if id_type == "VarChar":
            body["params"] = {
                "max_length": 255
            }
        
        response = openapi_client.data_plane_api_request(
            endpoint=endpoint,
            uri="/v2/vectordb/collections/create",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Log results
        logger.info(f"CREATE_COLLECTION RESULT: collection created successfully")
        
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"CREATE_COLLECTION ERROR: {str(e)}")
        raise Exception(f"Failed to create collection: {str(e)}") from e


@zilliz_mcp.tool()
async def describe_collection(
    cluster_id: str, 
    region_id: str, 
    endpoint: str,
    collection_name: str,
    db_name: str = ""
) -> str:
    """
    Describe the details of a collection.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        endpoint: The cluster endpoint URL. Can be obtained by calling describe_cluster and using the connect_address field
        collection_name: The name of the collection to describe
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
    Returns:
        Dict containing detailed information about the specified collection
        Example:
        {
            "code": 0,
            "data": {
                "aliases": [],
                "autoId": false,
                "collectionID": 448707763883002000,
                "collectionName": "test_collection",
                "consistencyLevel": "Bounded",
                "description": "",
                "enableDynamicField": true,
                "fields": [
                    {
                        "autoId": false,
                        "description": "",
                        "id": 100,
                        "name": "id",
                        "partitionKey": false,
                        "primaryKey": true,
                        "type": "Int64"
                    },
                    {
                        "autoId": false,
                        "description": "",
                        "id": 101,
                        "name": "vector",
                        "params": [
                            {
                                "key": "dim",
                                "value": "5"
                            }
                        ],
                        "partitionKey": false,
                        "primaryKey": false,
                        "type": "FloatVector"
                    }
                ],
                "indexes": [
                    {
                        "fieldName": "vector",
                        "indexName": "vector",
                        "metricType": "COSINE"
                    }
                ],
                "load": "LoadStateLoaded",
                "partitionsNum": 1,
                "properties": []
            }
        }
        
    """
    try:
        # Log request
        logger.info(f"DESCRIBE_COLLECTION: collection_name={collection_name}, cluster_id={cluster_id}")
        
        # Build request body
        body = {
            "collectionName": collection_name
        }
        
        # Add dbName only if provided
        if db_name:
            body["dbName"] = db_name
        
        response = openapi_client.data_plane_api_request(
            endpoint=endpoint,
            uri="/v2/vectordb/collections/describe",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Log results
        data = response.get('data', {})
        fields_count = len(data.get('fields', []))
        logger.info(f"DESCRIBE_COLLECTION RESULT: {fields_count} fields found")
        
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"DESCRIBE_COLLECTION ERROR: {str(e)}")
        raise Exception(f"Failed to describe collection: {str(e)}") from e


@zilliz_mcp.tool()
async def insert_entities(
    cluster_id: str,
    region_id: str, 
    endpoint: str,
    collection_name: str,
    data: Union[Dict[str, Any], List[Dict[str, Any]]],
    db_name: str = ""
) -> str:
    """
    Insert data into a specific collection.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        endpoint: The cluster endpoint URL. Can be obtained by calling describe_cluster and using the connect_address field
        collection_name: The name of an existing collection
        data: An entity object or an array of entity objects. Note that the keys in an entity object should match the collection schema
        db_name: The name of the target database. Pass explicit dbName or leave empty when cluster is free or serverless
    Returns:
        Dict containing the response with insert count and insert IDs
        Example:
        {
            "code": 0,
            "data": {
                "insertCount": 10,
                "insertIds": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
            }
        }
        
    """
    try:
        # Log request
        data_count = len(data) if isinstance(data, list) else 1
        logger.info(f"INSERT_ENTITIES: collection_name={collection_name}, data_count={data_count}, cluster_id={cluster_id}")
        
        # Build request body
        body = {
            "collectionName": collection_name,
            "data": data
        }
        
        # Add dbName only if provided
        if db_name:
            body["dbName"] = db_name
        
        response = openapi_client.data_plane_api_request(
            endpoint=endpoint,
            uri="/v2/vectordb/entities/insert",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Log results
        response_data = response.get('data', {})
        insert_count = response_data.get('insertCount', 0)
        logger.info(f"INSERT_ENTITIES RESULT: {insert_count} entities inserted")
        
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"INSERT_ENTITIES ERROR: {str(e)}")
        raise Exception(f"Failed to insert data: {str(e)}") from e


@zilliz_mcp.tool()
async def delete_entities(
    cluster_id: str,
    region_id: str,
    endpoint: str,
    collection_name: str,
    filter: str,
    db_name: str = "",
    partition_name: str = ""
) -> str:
    """
    Delete entities from a collection by filtering conditions or primary keys.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        endpoint: The cluster endpoint URL. Can be obtained by calling describe_cluster and using the connect_address field
        collection_name: The name of an existing collection
        filter: A scalar filtering condition to filter matching entities. You can set this parameter to an empty string to skip scalar filtering. To build a scalar filtering condition, refer to Reference on Scalar Filters
        db_name: The name of the target database. Pass explicit dbName or leave empty when cluster is free or serverless
        partition_name: The name of a partition in the current collection. If specified, the data is to be deleted from the specified partition
    Returns:
        Dict containing the response
        Example:
        {
            "code": 0,
            "cost": 0,
            "data": {}
        }
        
    """
    try:
        # Log request
        logger.info(f"DELETE_ENTITIES: collection_name={collection_name}, filter={filter}, cluster_id={cluster_id}")
        
        # Build request body
        body = {
            "collectionName": collection_name,
            "filter": filter
        }
        
        # Add dbName only if provided
        if db_name:
            body["dbName"] = db_name
            
        # Add partitionName only if provided
        if partition_name:
            body["partitionName"] = partition_name
        
        response = openapi_client.data_plane_api_request(
            endpoint=endpoint,
            uri="/v2/vectordb/entities/delete",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Log results
        logger.info(f"DELETE_ENTITIES RESULT: deletion completed")
        
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"DELETE_ENTITIES ERROR: {str(e)}")
        raise Exception(f"Failed to delete entities: {str(e)}") from e


@zilliz_mcp.tool()
async def search(
    cluster_id: str,
    region_id: str,
    endpoint: str,
    collection_name: str,
    data: List[List[float]],
    anns_field: str,
    limit: int = 10,
    db_name: str = "",
    filter: str = "",
    offset: int = 0,
    grouping_field: str = "",
    output_fields: Optional[List[str]] = None,
    metric_type: str = "",
    search_params: Optional[Dict[str, Any]] = None,
    partition_names: Optional[List[str]] = None,
    consistency_level: str = ""
) -> str:
    """
    Conduct a vector similarity search with an optional scalar filtering expression.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        endpoint: The cluster endpoint URL. Can be obtained by calling describe_cluster and using the connect_address field
        collection_name: The name of the collection to which this operation applies
        data: A list of vector embeddings. Zilliz Cloud searches for the most similar vector embeddings to the specified ones
        anns_field: The name of the vector field
        limit: The total number of entities to return (default: 10). The sum of this value and offset should be less than 16,384
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
        filter: The filter used to find matches for the search
        offset: The number of records to skip in the search result. The sum of this value and limit should be less than 16,384
        grouping_field: The name of the field that serves as the aggregation criteria
        output_fields: An array of fields to return along with the search results
        metric_type: The name of the metric type that applies to the current search (L2, IP, COSINE)
        search_params: Extra search parameters including radius and range_filter
        partition_names: The name of the partitions to which this operation applies
        consistency_level: The consistency level of the search operation (Strong, Eventually, Bounded)
    Returns:
        Dict containing the search results
        Example:
        {
            "code": 0,
            "data": [
                {
                    "color": "orange_6781",
                    "distance": 1,
                    "id": 448300048035776800
                },
                {
                    "color": "red_4794", 
                    "distance": 0.9353201,
                    "id": 448300048035776800
                }
            ]
        }
        
    """
    try:
        # Log request
        vectors_count = len(data)
        logger.info(f"SEARCH: collection_name={collection_name}, vectors_count={vectors_count}, limit={limit}, cluster_id={cluster_id}")
        
        # Build request body
        body = {
            "collectionName": collection_name,
            "data": data,
            "annsField": anns_field,
            "limit": limit
        }
        
        # Add dbName only if provided
        if db_name:
            body["dbName"] = db_name
            
        # Add filter only if provided
        if filter:
            body["filter"] = filter
            
        # Add offset only if provided and not 0
        if offset > 0:
            body["offset"] = offset
            
        # Add groupingField only if provided
        if grouping_field:
            body["groupingField"] = grouping_field
            
        # Add outputFields only if provided
        if output_fields:
            body["outputFields"] = output_fields
            
        # Add searchParams if metric_type or search_params provided
        if metric_type or search_params:
            search_params_obj = {}
            if metric_type:
                search_params_obj["metricType"] = metric_type
            if search_params:
                search_params_obj["params"] = search_params
            body["searchParams"] = search_params_obj
            
        # Add partitionNames only if provided
        if partition_names:
            body["partitionNames"] = partition_names
            
        # Add consistencyLevel only if provided
        if consistency_level:
            body["consistencyLevel"] = consistency_level
        
        response = openapi_client.data_plane_api_request(
            endpoint=endpoint,
            uri="/v2/vectordb/entities/search",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Log results
        results = response.get('data', [])
        results_count = len(results)
        logger.info(f"SEARCH RESULT: {results_count} results found")
        
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"SEARCH ERROR: {str(e)}")
        raise Exception(f"Failed to search entities: {str(e)}") from e


@zilliz_mcp.tool()
async def query(
    cluster_id: str,
    region_id: str,
    endpoint: str,
    collection_name: str,
    filter: str,
    db_name: str = "",
    output_fields: Optional[List[str]] = None,
    partition_names: Optional[List[str]] = None,
    limit: int = 100,
    offset: int = 0
) -> str:
    """
    Conduct a filtering on the scalar field with a specified boolean expression.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        endpoint: The cluster endpoint URL. Can be obtained by calling describe_cluster and using the connect_address field
        collection_name: The name of the collection to which this operation applies
        filter: The filter used to find matches for the search
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
        output_fields: An array of fields to return along with the query results
        partition_names: The name of the partitions to which this operation applies. If not set, the operation applies to all partitions in the collection
        limit: The total number of entities to return (default: 10000). The sum of this value and offset should be less than 16,384
        offset: The number of records to skip in the search result. The sum of this value and limit should be less than 16,384
    Returns:
        Dict containing the query results
        Example:
        {
            "code": 0,
            "cost": 0,
            "data": [
                {
                    "color": "red_7025",
                    "id": 1
                },
                {
                    "color": "red_4794",
                    "id": 4
                },
                {
                    "color": "red_9392",
                    "id": 6
                }
            ]
        }
        
    """
    try:
        # Log request
        logger.info(f"QUERY: collection_name={collection_name}, filter={filter}, cluster_id={cluster_id}")
        
        # Build request body
        body = {
            "collectionName": collection_name,
            "filter": filter,
            "limit": limit,
        }
        
        # Add dbName only if provided
        if db_name:
            body["dbName"] = db_name
            
        # Add outputFields only if provided
        if output_fields:
            body["outputFields"] = output_fields
            
        # Add partitionNames only if provided
        if partition_names:
            body["partitionNames"] = partition_names
            
            
        # Add offset only if provided and not 0
        if offset > 0:
            body["offset"] = offset
        
        response = openapi_client.data_plane_api_request(
            endpoint=endpoint,
            uri="/v2/vectordb/entities/query",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Log results
        results = response.get('data', [])
        results_count = len(results)
        logger.info(f"QUERY RESULT: {results_count} entities found")
        
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"QUERY ERROR: {str(e)}")
        raise Exception(f"Failed to query entities: {str(e)}") from e


@zilliz_mcp.tool()
async def hybrid_search(
    cluster_id: str,
    region_id: str,
    endpoint: str,
    collection_name: str,
    search_requests: List[Dict[str, Any]],
    rerank_strategy: str,
    rerank_params: Dict[str, Any],
    limit: int,
    db_name: str = "",
    partition_names: Optional[List[str]] = None,
    output_fields: Optional[List[str]] = None,
    consistency_level: str = ""
) -> str:
    """
    Search for entities based on vector similarity and scalar filtering and rerank the results using a specified strategy.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        endpoint: The cluster endpoint URL. Can be obtained by calling describe_cluster and using the connect_address field
        collection_name: The name of the collection to which this operation applies
        search_requests: List of search parameters for different vector fields. Each search request should contain:
            - data: A list of vector embeddings
            - annsField: The name of the vector field
            - filter: A boolean expression filter (optional)
            - groupingField: The name of the field that serve as the aggregation criteria (optional)
            - metricType: The metric type (L2, IP, COSINE) (optional)
            - limit: The number of entities to return
            - offset: The number of entities to skip (optional, default: 0)
            - ignoreGrowing: Whether to ignore entities in growing segments (optional, default: false)
            - params: Extra search parameters with radius and range_filter (optional)
        rerank_strategy: The name of the reranking strategy (rrf, weighted)
        rerank_params: Parameters related to the specified strategy (e.g., {"k": 10} for rrf)
        limit: The total number of entities to return. The sum of this value and offset should be less than 16,384
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
        partition_names: The name of the partitions to which this operation applies
        output_fields: An array of fields to return along with the search results
        consistency_level: The consistency level of the search operation (Strong, Eventually, Bounded)
    Returns:
        Dict containing the hybrid search results
        Example:
        {
            "code": 0,
            "cost": 0,
            "data": [
                {
                    "book_describe": "book_105",
                    "distance": 0.09090909,
                    "id": 450519760774180800,
                    "user_id": 5,
                    "word_count": 105
                }
            ]
        }
        
    """
    try:
        # Log request
        search_requests_count = len(search_requests)
        logger.info(f"HYBRID_SEARCH: collection_name={collection_name}, search_requests_count={search_requests_count}, strategy={rerank_strategy}, cluster_id={cluster_id}")
        
        # Build request body
        body = {
            "collectionName": collection_name,
            "search": search_requests,
            "rerank": {
                "strategy": rerank_strategy,
                "params": rerank_params
            },
            "limit": limit
        }
        
        # Add dbName only if provided
        if db_name:
            body["dbName"] = db_name
            
        # Add partitionNames only if provided
        if partition_names:
            body["partitionNames"] = partition_names
            
        # Add outputFields only if provided
        if output_fields:
            body["outputFields"] = output_fields
            
        # Add consistencyLevel only if provided
        if consistency_level:
            body["consistencyLevel"] = consistency_level
        
        response = openapi_client.data_plane_api_request(
            endpoint=endpoint,
            uri="/v2/vectordb/entities/hybrid_search",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Log results
        results = response.get('data', [])
        results_count = len(results)
        logger.info(f"HYBRID_SEARCH RESULT: {results_count} results found")
        
        return json.dumps(response)
        
    except Exception as e:
        logger.error(f"HYBRID_SEARCH ERROR: {str(e)}")
        raise Exception(f"Failed to perform hybrid search: {str(e)}") from e
    
    



