"""
Unit tests for zilliz_mcp_server.tools.milvus.milvus_tools module.

Tests data plane operations like database, collection, and data management.
"""

import json
import pytest
from unittest.mock import patch, Mock

# Enable asyncio for all async tests in this module
pytestmark = pytest.mark.asyncio


# Mock the MCP app to avoid import issues during testing
@pytest.fixture(autouse=True)
def mock_zilliz_mcp():
    """Mock the zilliz_mcp app for testing."""
    with patch('zilliz_mcp_server.tools.milvus.milvus_tools.zilliz_mcp') as mock_app:
        mock_app.tool.return_value = lambda func: func  # Return function unchanged
        yield mock_app


@pytest.fixture
def sample_collection_response():
    """Sample collection describe response."""
    return {
        "code": 0,
        "data": {
            "collectionName": "test_collection",
            "collectionID": 448707763883002000,
            "fields": [
                {
                    "id": 100,
                    "name": "id",
                    "type": "Int64",
                    "primaryKey": True
                },
                {
                    "id": 101,
                    "name": "vector",
                    "type": "FloatVector",
                    "params": [{"key": "dim", "value": "5"}]
                }
            ],
            "load": "LoadStateLoaded",
            "indexes": [
                {
                    "fieldName": "vector",
                    "indexName": "vector",
                    "metricType": "COSINE"
                }
            ]
        }
    }


class TestListDatabases:
    """Test cases for list_databases function."""

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_list_databases_success(self, mock_client):
        """Test successful database listing."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import list_databases
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "data": ["default", "test_db"]
        }
        
        result = await list_databases("cluster1", "region1", "https://test.endpoint.com")
        result_data = json.loads(result)
        
        assert result_data == ["default", "test_db"]
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/databases/list",
            cluster_id="cluster1",
            region_id="region1",
            body_map={},
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_list_databases_api_error(self, mock_client):
        """Test database listing with API error."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import list_databases
        
        mock_client.data_plane_api_request.side_effect = Exception("Connection failed")
        
        with pytest.raises(Exception, match="Failed to list databases: Connection failed"):
            await list_databases("cluster1", "region1", "https://test.endpoint.com")


class TestListCollections:
    """Test cases for list_collections function."""

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_list_collections_success(self, mock_client):
        """Test successful collection listing."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import list_collections
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "data": ["collection1", "collection2"]
        }
        
        result = await list_collections("cluster1", "region1", "https://test.endpoint.com", "test_db")
        result_data = json.loads(result)
        
        assert result_data == ["collection1", "collection2"]
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/collections/list",
            cluster_id="cluster1",
            region_id="region1",
            body_map={"dbName": "test_db"},
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_list_collections_no_db_name(self, mock_client):
        """Test collection listing without database name."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import list_collections
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "data": ["collection1"]
        }
        
        result = await list_collections("cluster1", "region1", "https://test.endpoint.com")
        
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/collections/list",
            cluster_id="cluster1",
            region_id="region1",
            body_map={},
            method="POST"
        )


class TestCreateCollection:
    """Test cases for create_collection function."""

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_create_collection_success(self, mock_client):
        """Test successful collection creation."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import create_collection
        
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": {}}
        
        result = await create_collection(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            dimension=128
        )
        
        result_data = json.loads(result)
        assert result_data == {"code": 0, "data": {}}
        
        expected_body = {
            "collectionName": "test_collection",
            "dimension": 128,
            "metricType": "COSINE",
            "idType": "Int64",
            "autoID": True,
            "primaryFieldName": "id",
            "vectorFieldName": "vector"
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/collections/create",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_create_collection_with_varchar_id(self, mock_client):
        """Test collection creation with VarChar ID type."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import create_collection
        
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": {}}
        
        result = await create_collection(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            dimension=128,
            id_type="VarChar"
        )
        
        expected_body = {
            "collectionName": "test_collection",
            "dimension": 128,
            "metricType": "COSINE",
            "idType": "VarChar",
            "autoID": True,
            "primaryFieldName": "id",
            "vectorFieldName": "vector",
            "params": {"max_length": 255}
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/collections/create",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_create_collection_with_db_name(self, mock_client):
        """Test collection creation with database name."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import create_collection
        
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": {}}
        
        result = await create_collection(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            dimension=128,
            db_name="test_db"
        )
        
        # Verify dbName is included in the body
        call_args = mock_client.data_plane_api_request.call_args
        assert call_args[1]['body_map']['dbName'] == "test_db"


class TestDescribeCollection:
    """Test cases for describe_collection function."""

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_describe_collection_success(self, mock_client, sample_collection_response):
        """Test successful collection description."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import describe_collection
        
        mock_client.data_plane_api_request.return_value = sample_collection_response
        
        result = await describe_collection(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection"
        )
        
        result_data = json.loads(result)
        assert result_data == sample_collection_response
        
        expected_body = {"collectionName": "test_collection"}
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/collections/describe",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )


class TestInsertEntities:
    """Test cases for insert_entities function."""

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_insert_entities_success(self, mock_client):
        """Test successful entity insertion."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import insert_entities
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "data": {"insertCount": 2, "insertIds": [1, 2]}
        }
        
        test_data = [
            {"id": 1, "vector": [0.1, 0.2, 0.3]},
            {"id": 2, "vector": [0.4, 0.5, 0.6]}
        ]
        
        result = await insert_entities(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            data=test_data
        )
        
        result_data = json.loads(result)
        assert result_data["data"]["insertCount"] == 2
        assert result_data["data"]["insertIds"] == [1, 2]
        
        expected_body = {
            "collectionName": "test_collection",
            "data": test_data
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/entities/insert",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_insert_entities_single_entity(self, mock_client):
        """Test insertion of single entity."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import insert_entities
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "data": {"insertCount": 1, "insertIds": [1]}
        }
        
        test_data = {"id": 1, "vector": [0.1, 0.2, 0.3]}
        
        result = await insert_entities(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            data=test_data
        )
        
        # Verify single entity is handled correctly
        call_args = mock_client.data_plane_api_request.call_args
        assert call_args[1]['body_map']['data'] == test_data


class TestSearch:
    """Test cases for search function."""

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_search_success(self, mock_client):
        """Test successful vector search."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import search
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "data": [
                {"id": 1, "distance": 0.1, "vector": [0.1, 0.2, 0.3]},
                {"id": 2, "distance": 0.2, "vector": [0.4, 0.5, 0.6]}
            ]
        }
        
        search_vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        
        result = await search(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            data=search_vectors,
            anns_field="vector",
            limit=10
        )
        
        result_data = json.loads(result)
        assert len(result_data["data"]) == 2
        
        expected_body = {
            "collectionName": "test_collection",
            "data": search_vectors,
            "annsField": "vector",
            "limit": 10
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/entities/search",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_search_with_filter(self, mock_client):
        """Test vector search with filter."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import search
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "data": [{"id": 1, "distance": 0.1}]
        }
        
        search_vectors = [[0.1, 0.2, 0.3]]
        
        result = await search(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            data=search_vectors,
            anns_field="vector",
            filter="id > 0",
            output_fields=["id", "name"]
        )
        
        # Verify filter and output fields are included
        call_args = mock_client.data_plane_api_request.call_args
        body = call_args[1]['body_map']
        assert body['filter'] == "id > 0"
        assert body['outputFields'] == ["id", "name"]


class TestQuery:
    """Test cases for query function."""

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_query_success(self, mock_client):
        """Test successful scalar query."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import query
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "data": [
                {"id": 1, "name": "test1"},
                {"id": 2, "name": "test2"}
            ]
        }
        
        result = await query(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            filter="id > 0"
        )
        
        result_data = json.loads(result)
        assert len(result_data["data"]) == 2
        
        expected_body = {
            "collectionName": "test_collection",
            "filter": "id > 0",
            "limit": 100
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/entities/query",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_query_with_limit_and_output_fields(self, mock_client):
        """Test query with limit and output fields."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import query
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "data": [{"id": 1, "name": "test1"}]
        }
        
        result = await query(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            filter="id > 0",
            limit=100,
            output_fields=["id", "name"]
        )
        
        # Verify limit and output fields are included
        call_args = mock_client.data_plane_api_request.call_args
        body = call_args[1]['body_map']
        assert body['limit'] == 100
        assert body['outputFields'] == ["id", "name"]


class TestDeleteEntities:
    """Test cases for delete_entities function."""

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_delete_entities_success(self, mock_client):
        """Test successful entity deletion."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import delete_entities
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "cost": 0,
            "data": {}
        }
        
        result = await delete_entities(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            filter="id in [1, 2, 3]"
        )
        
        result_data = json.loads(result)
        assert result_data["code"] == 0
        
        expected_body = {
            "collectionName": "test_collection",
            "filter": "id in [1, 2, 3]"
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/entities/delete",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_delete_entities_with_db_and_partition(self, mock_client):
        """Test entity deletion with database and partition names."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import delete_entities
        
        mock_client.data_plane_api_request.return_value = {
            "code": 0,
            "cost": 0,
            "data": {}
        }
        
        result = await delete_entities(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            filter="id in [1, 2, 3]",
            db_name="test_db",
            partition_name="test_partition"
        )
        
        expected_body = {
            "collectionName": "test_collection",
            "filter": "id in [1, 2, 3]",
            "dbName": "test_db",
            "partitionName": "test_partition"
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/entities/delete",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )


class TestHybridSearch:
    """Test cases for hybrid_search function."""

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_hybrid_search_success(self, mock_client):
        """Test successful hybrid search."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import hybrid_search
        
        mock_response = {
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
        mock_client.data_plane_api_request.return_value = mock_response
        
        search_requests = [
            {
                "data": [[0.1, 0.2, 0.3, 0.4, 0.5]],
                "annsField": "vector",
                "metricType": "COSINE",
                "limit": 100
            },
            {
                "data": [[0.5, 0.4, 0.3, 0.2, 0.1]],
                "annsField": "dense_vector",
                "metricType": "L2",
                "limit": 100
            }
        ]
        
        rerank_params = {"k": 10}
        
        result = await hybrid_search(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            search_requests=search_requests,
            rerank_strategy="rrf",
            rerank_params=rerank_params,
            limit=10
        )
        
        result_data = json.loads(result)
        assert result_data == mock_response
        
        expected_body = {
            "collectionName": "test_collection",
            "search": search_requests,
            "rerank": {
                "strategy": "rrf",
                "params": {"k": 10}
            },
            "limit": 10
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/entities/hybrid_search",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_hybrid_search_with_all_params(self, mock_client):
        """Test hybrid search with all optional parameters."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import hybrid_search
        
        mock_response = {
            "code": 0,
            "cost": 0,
            "data": []
        }
        mock_client.data_plane_api_request.return_value = mock_response
        
        search_requests = [
            {
                "data": [[0.1, 0.2, 0.3, 0.4, 0.5]],
                "annsField": "vector",
                "metricType": "COSINE",
                "limit": 100,
                "filter": "user_id > 0",
                "offset": 0,
                "ignoreGrowing": False,
                "params": {"radius": 0.8, "range_filter": 0.2}
            }
        ]
        
        rerank_params = {"weights": [0.7, 0.3]}
        
        result = await hybrid_search(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            search_requests=search_requests,
            rerank_strategy="weighted",
            rerank_params=rerank_params,
            limit=20,
            db_name="test_db",
            partition_names=["partition1", "partition2"],
            output_fields=["id", "user_id", "book_describe"],
            consistency_level="Strong"
        )
        
        result_data = json.loads(result)
        assert result_data == mock_response
        
        expected_body = {
            "collectionName": "test_collection",
            "search": search_requests,
            "rerank": {
                "strategy": "weighted",
                "params": {"weights": [0.7, 0.3]}
            },
            "limit": 20,
            "dbName": "test_db",
            "partitionNames": ["partition1", "partition2"],
            "outputFields": ["id", "user_id", "book_describe"],
            "consistencyLevel": "Strong"
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/entities/hybrid_search",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_hybrid_search_single_request(self, mock_client):
        """Test hybrid search with single search request."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import hybrid_search
        
        mock_response = {
            "code": 0,
            "cost": 0,
            "data": [
                {
                    "id": 1,
                    "distance": 0.5,
                    "title": "Test Document"
                }
            ]
        }
        mock_client.data_plane_api_request.return_value = mock_response
        
        search_requests = [
            {
                "data": [[0.1, 0.2, 0.3, 0.4, 0.5]],
                "annsField": "vector",
                "limit": 50
            }
        ]
        
        result = await hybrid_search(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            search_requests=search_requests,
            rerank_strategy="rrf",
            rerank_params={"k": 5},
            limit=5
        )
        
        result_data = json.loads(result)
        assert result_data == mock_response
        assert len(result_data["data"]) == 1

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_hybrid_search_empty_results(self, mock_client):
        """Test hybrid search with empty results."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import hybrid_search
        
        mock_response = {
            "code": 0,
            "cost": 0,
            "data": []
        }
        mock_client.data_plane_api_request.return_value = mock_response
        
        search_requests = [
            {
                "data": [[0.1, 0.2, 0.3, 0.4, 0.5]],
                "annsField": "vector",
                "limit": 50,
                "filter": "id < 0"  # Filter that matches nothing
            }
        ]
        
        result = await hybrid_search(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            search_requests=search_requests,
            rerank_strategy="rrf",
            rerank_params={"k": 10},
            limit=10
        )
        
        result_data = json.loads(result)
        assert result_data == mock_response
        assert len(result_data["data"]) == 0

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_hybrid_search_api_error(self, mock_client):
        """Test hybrid search with API error."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import hybrid_search
        
        mock_client.data_plane_api_request.side_effect = Exception("Connection failed")
        
        search_requests = [
            {
                "data": [[0.1, 0.2, 0.3, 0.4, 0.5]],
                "annsField": "vector",
                "limit": 50
            }
        ]
        
        with pytest.raises(Exception, match="Failed to perform hybrid search: Connection failed"):
            await hybrid_search(
                cluster_id="cluster1",
                region_id="region1",
                endpoint="https://test.endpoint.com",
                collection_name="test_collection",
                search_requests=search_requests,
                rerank_strategy="rrf",
                rerank_params={"k": 10},
                limit=10
            )

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_hybrid_search_multiple_vectors_per_request(self, mock_client):
        """Test hybrid search with multiple vectors in search request."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import hybrid_search
        
        mock_response = {
            "code": 0,
            "cost": 0,
            "data": [
                {
                    "id": 1,
                    "distance": 0.1,
                    "title": "Document 1"
                },
                {
                    "id": 2,
                    "distance": 0.2,
                    "title": "Document 2"
                }
            ]
        }
        mock_client.data_plane_api_request.return_value = mock_response
        
        search_requests = [
            {
                "data": [
                    [0.1, 0.2, 0.3, 0.4, 0.5],
                    [0.5, 0.4, 0.3, 0.2, 0.1]
                ],
                "annsField": "vector",
                "limit": 100
            }
        ]
        
        result = await hybrid_search(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            search_requests=search_requests,
            rerank_strategy="rrf",
            rerank_params={"k": 10},
            limit=10
        )
        
        result_data = json.loads(result)
        assert result_data == mock_response
        assert len(result_data["data"]) == 2

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_hybrid_search_with_grouping_field(self, mock_client):
        """Test hybrid search with grouping field in search request."""
        from zilliz_mcp_server.tools.milvus.milvus_tools import hybrid_search
        
        mock_response = {
            "code": 0,
            "cost": 0,
            "data": [
                {
                    "id": 1,
                    "distance": 0.1,
                    "category": "tech",
                    "title": "Tech Document"
                }
            ]
        }
        mock_client.data_plane_api_request.return_value = mock_response
        
        search_requests = [
            {
                "data": [[0.1, 0.2, 0.3, 0.4, 0.5]],
                "annsField": "vector",
                "limit": 100,
                "groupingField": "category"
            }
        ]
        
        result = await hybrid_search(
            cluster_id="cluster1",
            region_id="region1",
            endpoint="https://test.endpoint.com",
            collection_name="test_collection",
            search_requests=search_requests,
            rerank_strategy="rrf",
            rerank_params={"k": 10},
            limit=10,
            output_fields=["id", "category", "title"]
        )
        
        result_data = json.loads(result)
        assert result_data == mock_response
        
        expected_body = {
            "collectionName": "test_collection",
            "search": search_requests,
            "rerank": {
                "strategy": "rrf",
                "params": {"k": 10}
            },
            "limit": 10,
            "outputFields": ["id", "category", "title"]
        }
        mock_client.data_plane_api_request.assert_called_once_with(
            endpoint="https://test.endpoint.com",
            uri="/v2/vectordb/entities/hybrid_search",
            cluster_id="cluster1",
            region_id="region1",
            body_map=expected_body,
            method="POST"
        ) 