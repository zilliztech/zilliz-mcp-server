"""Milvus Data Plane tools."""
import json
import logging
from typing import Dict, Any, List, Optional, Union
from pydantic import StrictBool
from zilliz_mcp_server.common import openapi_client
from zilliz_mcp_server.common import hints
from zilliz_mcp_server.common import budget
from zilliz_mcp_server.common import next_steps as ns
from zilliz_mcp_server.settings import config
from zilliz_mcp_server.app import zilliz_mcp, read_tool, write_tool

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

_dp_args = ns._dp


def _default_scalar_fields(cluster_id: str, region_id: str, db_name: str,
                           collection_name: str) -> "tuple[Optional[List[str]], List[str]]":
    """(non-vector field names, vector field names) for a query without output_fields.

    Returns (None, []) when the schema cannot be read, so the API default applies.
    """
    body: Dict[str, Any] = {"collectionName": collection_name}
    if db_name:
        body["dbName"] = db_name
    try:
        response = openapi_client.data_plane_api_request(
            uri="/v2/vectordb/collections/describe", cluster_id=cluster_id,
            region_id=region_id, body_map=body, method="POST")
    except Exception as e:  # the query itself will report real problems
        logger.info(f"describe before query failed, using API default output: {e}")
        return None, []
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return None, []
    fields = budget.scalar_fields(data)
    if not fields:
        return None, []
    vectors = [f.get("name") for f in data.get("fields", [])
               if isinstance(f, dict) and f.get("type") in budget.VECTOR_TYPES]
    return fields, vectors


def _budgeted(tool: str, results: Any, steps: List[Dict[str, Any]], notes: List[str],
              output_fields: Optional[List[str]], call_args: Dict[str, Any], paged: bool) -> str:
    """hints.ok(...) with rows trimmed to budget.RESULT_BUDGET and a note/next step if trimmed."""
    kept, info = budget.fit_rows(results)
    if info is None:
        return hints.ok(results, steps, notes)
    extra = []
    lean = budget.leaner_fields(results, output_fields)
    if lean:
        extra.append(hints.step(tool, "Same call without vector fields, so every row fits.",
                                **{**call_args, "output_fields": lean}))
    if paged and not lean and info["returned"] < info["total"]:
        args = {**call_args, "offset": call_args.get("offset", 0) + info["returned"],
                "limit": info["total"] - info["returned"]}
        if output_fields:
            args["output_fields"] = lean or output_fields
        extra.append(hints.step(tool, "Fetch the rows that were trimmed.", **args))
    return hints.ok(kept, extra + list(steps), [budget.trimmed_note(tool, info)] + list(notes))


@read_tool()
async def list_databases(cluster_id: str, region_id: str) -> str:
    """
    List all databases in the current cluster.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        List of database names
        Example:
        [
            "default",
            "test"
        ]
        
    """
    try:
        # Log request
        logger.info(f"LIST_DATABASES: cluster_id={cluster_id}")
        
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
        
        # Log results
        logger.info(f"LIST_DATABASES RESULT: {databases}")
        
        return hints.ok(databases, *ns.list_databases(databases, cluster_id, region_id))
        
    except Exception as e:
        logger.error(f"LIST_DATABASES ERROR: {str(e)}")
        raise hints.tool_error("list_databases", e, {"cluster_id": cluster_id, "region_id": region_id}) from e


@read_tool()
async def list_collections(cluster_id: str, region_id: str, db_name: str = "") -> str:
    """
    List all collection names in the specified database.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        db_name: The name of an existing database. Pass explicit dbName or leave empty when cluster is free or serverless
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
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
        logger.info(f"LIST_COLLECTIONS: cluster_id={cluster_id}, db_name={db_name}")
        
        response = openapi_client.data_plane_api_request(
            uri="/v2/vectordb/collections/list",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Extract collection names from response
        collections = response.get('data', [])
        
        # Log results
        logger.info(f"LIST_COLLECTIONS RESULT: {collections}")
        
        return hints.ok(collections, *ns.list_collections(collections, cluster_id, region_id, db_name))
        
    except Exception as e:
        logger.error(f"LIST_COLLECTIONS ERROR: {str(e)}")
        raise hints.tool_error("list_collections", e,
                               {"cluster_id": cluster_id, "region_id": region_id, "db_name": db_name}) from e


@write_tool(destructive=False)
async def create_collection(
    cluster_id: str, 
    region_id: str, 
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
        collection_name: The name of the collection to create
        dimension: The number of dimensions a vector value should have
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
        metric_type: The metric type (default: "COSINE", options: "L2", "IP", "COSINE") Ask the user to select the metric type, if user does not select, use default value "COSINE"
        id_type: The data type of the primary field (default: "Int64", options: "Int64", "VarChar")
        auto_id: Whether the primary field automatically increments (default: True)
        primary_field_name: The name of the primary field (default: "id")
        vector_field_name: The name of the vector field (default: "vector")
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        Dict containing the response
        Example (full envelope, hints omitted):
        {
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
            uri="/v2/vectordb/collections/create",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Log results
        logger.info(f"CREATE_COLLECTION RESULT: collection created successfully")
        
        return hints.ok(response.get('data', {}), *ns.create_collection(
            cluster_id, region_id, db_name, collection_name, dimension, auto_id,
            primary_field_name, vector_field_name))
        
    except Exception as e:
        logger.error(f"CREATE_COLLECTION ERROR: {str(e)}")
        raise hints.tool_error("create_collection", e, {
            "cluster_id": cluster_id, "region_id": region_id, "db_name": db_name,
            "collection_name": collection_name}) from e


@read_tool()
async def describe_collection(
    cluster_id: str, 
    region_id: str, 
    collection_name: str,
    db_name: str = ""
) -> str:
    """
    Describe the details of a collection.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        collection_name: The name of the collection to describe
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        Dict containing detailed information about the specified collection, plus
        "rowCount": number of entities in THIS collection (from collections/get_stats).
        Use rowCount to answer "how many rows/entities does collection X have" - the
        cluster metric ENTITIES_COUNT is the total across all collections of the cluster.
        rowCount is omitted (with a note) if the stats call fails.
        rowCount is approximate: right after inserts or deletes it can still include rows that
        were deleted or not yet flushed. For an exact count, use query with
        filter="" and output_fields=["count(*)"].
        Example (full envelope, hints omitted):
        {
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
                "properties": [],
                "rowCount": 20000
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

        # Row count of this collection (describe does not return it)
        stats_note = None
        try:
            stats = openapi_client.data_plane_api_request(
                uri="/v2/vectordb/collections/get_stats",
                cluster_id=cluster_id,
                region_id=region_id,
                body_map=body,
                method="POST"
            )
            row_count = (stats.get('data') or {}).get('rowCount')
            if row_count is not None:
                data['rowCount'] = int(row_count)
        except Exception as stats_err:
            logger.warning(f"DESCRIBE_COLLECTION get_stats failed: {stats_err}")
            stats_note = ("rowCount unavailable (collections/get_stats failed: "
                          f"{str(stats_err)[:120]}); use query with filter=\"\" and "
                          "output_fields=[\"count(*)\"] instead.")

        steps, notes = ns.describe_collection(data, cluster_id, region_id, db_name)
        if stats_note:
            notes = [stats_note] + list(notes)
        return hints.ok(data, steps, notes)
        
    except Exception as e:
        logger.error(f"DESCRIBE_COLLECTION ERROR: {str(e)}")
        raise hints.tool_error("describe_collection", e, {
            "cluster_id": cluster_id, "region_id": region_id, "db_name": db_name,
            "collection_name": collection_name}) from e


@write_tool(destructive=False)
async def insert_entities(
    cluster_id: str,
    region_id: str, 
    collection_name: str,
    data: Union[Dict[str, Any], List[Dict[str, Any]]],
    db_name: str = ""
) -> str:
    """
    Insert data into a specific collection.
    
    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        collection_name: The name of an existing collection
        data: An entity object or an array of entity objects. Note that the keys in an entity object should match the collection schema
        db_name: The name of the target database. Pass explicit dbName or leave empty when cluster is free or serverless
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        Dict containing the response with insert count and insert IDs
        Example (full envelope, hints omitted):
        {
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
        
        return hints.ok(response_data, *ns.insert_entities(response_data, data_count))
        
    except Exception as e:
        logger.error(f"INSERT_ENTITIES ERROR: {str(e)}")
        raise hints.tool_error("insert_entities", e, {
            "cluster_id": cluster_id, "region_id": region_id, "db_name": db_name,
            "collection_name": collection_name}) from e


def _delete_preview(cluster_id: str, region_id: str, collection_name: str, filter: str,
                    db_name: str, partition_name: str) -> str:
    """Count the entities a delete would remove, without deleting anything."""
    body = {"collectionName": collection_name, "filter": filter, "outputFields": ["count(*)"]}
    if db_name:
        body["dbName"] = db_name
    if partition_name:
        body["partitionNames"] = [partition_name]
    count = None
    count_error = None
    try:
        response = openapi_client.data_plane_api_request(
            uri="/v2/vectordb/entities/query", cluster_id=cluster_id, region_id=region_id,
            body_map=body, method="POST")
        rows = response.get('data') or []
        if rows and isinstance(rows[0], dict):
            count = rows[0].get('count(*)')
    except Exception as e:  # the preview must not block the user from confirming
        count_error = str(e)[:300]
    preview = {
        'confirm_required': True,
        'action': 'delete_entities',
        'collection_name': collection_name,
        'filter': filter,
        'matching_entities': count,
        'impact': "Deleting is irreversible: matching entities cannot be recovered.",
    }
    if db_name:
        preview['db_name'] = db_name
    if partition_name:
        preview['partition_name'] = partition_name
    if count_error:
        preview['count_error'] = count_error
    # Deliberately no next_steps: an executable suggestion with confirm=true would let an agent
    # skip the user's confirmation.
    preview['how_to_confirm'] = ("Show this to the user. Only if they explicitly agree, call "
                                 "delete_entities again with the same arguments and confirm=true.")
    return hints.ok(preview, None, ["Nothing was deleted."])


@write_tool(destructive=True, idempotent=True)
async def delete_entities(
    cluster_id: str,
    region_id: str,
    collection_name: str,
    filter: str,
    db_name: str = "",
    partition_name: str = "",
    confirm: StrictBool = False
) -> str:
    """
    Delete entities from a collection by filtering conditions or primary keys. IRREVERSIBLE:
    deleted entities cannot be recovered. Only call this when the user explicitly asks to
    delete data matching this filter.

    Two steps: call with confirm=false (default) to get a preview with the number of
    entities that match the filter, without deleting anything. Show it to the user and
    call again with the same arguments and confirm=true only after they confirm.

    Args:
        cluster_id: ID of the cluster
        region_id: ID of the cloud region hosting the cluster
        collection_name: The name of an existing collection
        filter: A scalar filtering condition or primary-key expression selecting the entities to delete, e.g. 'id in [1, 2]'. Required; an empty filter is rejected
        db_name: The name of the target database. Pass explicit dbName or leave empty when cluster is free or serverless
        partition_name: The name of a partition in the current collection. If specified, the data is to be deleted from the specified partition
        confirm: false (default) returns the preview only; true deletes the matching entities
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result> with confirm=false:
        {"confirm_required": true, "action": "delete_entities", "collection_name": "...",
        "filter": "...", "matching_entities": <int, or null if it could not be counted>,
        "impact": "..."}
        <result> with confirm=true:
        Dict containing the response
        Example (full envelope, hints omitted):
        {
            "data": {}
        }
        
    """
    try:
        # Log request
        logger.info(f"DELETE_ENTITIES: collection_name={collection_name}, filter={filter}, cluster_id={cluster_id}, confirm={confirm}")

        if not filter or not filter.strip():
            raise ValueError("filter is required for delete_entities; pass a condition such as 'id in [1, 2]'")

        if confirm is not True:
            return _delete_preview(cluster_id, region_id, collection_name, filter, db_name, partition_name)

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
            uri="/v2/vectordb/entities/delete",
            cluster_id=cluster_id,
            region_id=region_id,
            body_map=body,
            method="POST"
        )
        
        # Log results
        logger.info(f"DELETE_ENTITIES RESULT: deletion completed")
        
        return hints.ok(response.get('data', {}), *ns.delete_entities(
            cluster_id, region_id, db_name, collection_name, filter))
        
    except Exception as e:
        logger.error(f"DELETE_ENTITIES ERROR: {str(e)}")
        raise hints.tool_error("delete_entities", e, {
            "cluster_id": cluster_id, "region_id": region_id, "db_name": db_name,
            "collection_name": collection_name, "filter": filter}) from e


@read_tool()
async def search(
    cluster_id: str,
    region_id: str,
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
        collection_name: The name of the collection to which this operation applies
        data: A list of vector embeddings. Zilliz Cloud searches for the most similar vector embeddings to the specified ones
        anns_field: The name of the vector field
        limit: The total number of entities to return (default: 10). limit + offset must be at most 16,384
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
        filter: The filter used to find matches for the search
        offset: The number of records to skip in the search result. limit + offset must be at most 16,384
        grouping_field: The name of the field that serves as the aggregation criteria
        output_fields: An array of fields to return along with the search results. Default returns only
            id and distance. Avoid "*" or vector fields unless you need raw embeddings: a 1024-dim
            vector is ~14 KB of JSON per hit, and results over ~45 KB are trimmed (see notes).
        metric_type: The name of the metric type that applies to the current search (L2, IP, COSINE)
        search_params: Extra search parameters including radius and range_filter
        partition_names: The name of the partitions to which this operation applies
        consistency_level: The consistency level of the search operation (Strong, Session, Bounded, Eventually, Customized; the server default is Bounded)
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        Dict containing the search results
        Example (full envelope, hints omitted):
        {
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
        
        steps, notes = ns.search(results, cluster_id, region_id, db_name, collection_name,
                                 filter, output_fields)
        return _budgeted("search", results, steps, notes, output_fields, {
            **_dp_args(cluster_id, region_id, db_name), "collection_name": collection_name,
            "data": "<same query vectors>", "anns_field": anns_field, "filter": filter,
            "limit": limit, "offset": offset}, paged=True)
        
    except Exception as e:
        logger.error(f"SEARCH ERROR: {str(e)}")
        raise hints.tool_error("search", e, {
            "cluster_id": cluster_id, "region_id": region_id, "db_name": db_name,
            "collection_name": collection_name, "anns_field": anns_field, "filter": filter}) from e


@read_tool()
async def query(
    cluster_id: str,
    region_id: str,
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
        collection_name: The name of the collection to which this operation applies
        filter: The filter used to find matches for the search
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
        output_fields: An array of fields to return along with the query results. If omitted, all
            non-vector fields are returned (vector fields are left out; name them explicitly, or pass
            ["*"], to get raw embeddings). Results over ~45 KB of JSON are trimmed (see notes).
        partition_names: The name of the partitions to which this operation applies. If not set, the operation applies to all partitions in the collection
        limit: The total number of entities to return (default: 100). limit + offset must be at most 16,384
        offset: The number of records to skip in the query result. limit + offset must be at most 16,384
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        Dict containing the query results
        Example (full envelope, hints omitted):
        {
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
            
        # Add outputFields only if provided; otherwise leave vector fields out by default
        omitted_vectors: List[str] = []
        if output_fields:
            body["outputFields"] = output_fields
        else:
            fields, omitted_vectors = _default_scalar_fields(cluster_id, region_id, db_name, collection_name)
            if fields:
                body["outputFields"] = fields
            
        # Add partitionNames only if provided
        if partition_names:
            body["partitionNames"] = partition_names
            
            
        # Add offset only if provided and not 0
        if offset > 0:
            body["offset"] = offset
        
        response = openapi_client.data_plane_api_request(
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
        
        steps, notes = ns.query(results, cluster_id, region_id, db_name, collection_name,
                                filter, limit, offset, output_fields)
        if omitted_vectors and results:
            notes = [f"Vector field(s) {', '.join(omitted_vectors)} omitted by default; pass them in "
                     f"output_fields to get the raw embeddings."] + list(notes)
        return _budgeted("query", results, steps, notes, output_fields, {
            **_dp_args(cluster_id, region_id, db_name), "collection_name": collection_name,
            "filter": filter, "limit": limit, "offset": offset}, paged=True)
        
    except Exception as e:
        logger.error(f"QUERY ERROR: {str(e)}")
        raise hints.tool_error("query", e, {
            "cluster_id": cluster_id, "region_id": region_id, "db_name": db_name,
            "collection_name": collection_name, "filter": filter}) from e


@read_tool()
async def hybrid_search(
    cluster_id: str,
    region_id: str,
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
        limit: The total number of entities to return after reranking (at most 16,384)
        db_name: The name of the database. Pass explicit dbName or leave empty when cluster is free or serverless
        partition_names: The name of the partitions to which this operation applies
        output_fields: An array of fields to return along with the search results. Avoid vector
            fields unless you need raw embeddings; results over ~45 KB of JSON are trimmed (see notes).
        consistency_level: The consistency level of the search operation (Strong, Session, Bounded, Eventually, Customized; the server default is Bounded)
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        Dict containing the hybrid search results
        Example (full envelope, hints omitted):
        {
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
        
        steps, notes = ns.hybrid_search(results)
        return _budgeted("hybrid_search", results, steps, notes, output_fields, {
            **_dp_args(cluster_id, region_id, db_name), "collection_name": collection_name,
            "search_requests": "<same search_requests>", "rerank_strategy": rerank_strategy,
            "rerank_params": rerank_params, "limit": limit}, paged=False)
        
    except Exception as e:
        logger.error(f"HYBRID_SEARCH ERROR: {str(e)}")
        raise hints.tool_error("hybrid_search", e, {
            "cluster_id": cluster_id, "region_id": region_id, "db_name": db_name,
            "collection_name": collection_name}) from e
    
    



