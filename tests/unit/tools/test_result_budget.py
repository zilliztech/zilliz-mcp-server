"""Tests for result size budget (common/budget.py) and its use in search/query/hybrid_search."""
import json
from unittest.mock import patch

import pytest

from zilliz_mcp_server.common import budget

VEC = [0.0123456789] * 1024
SCHEMA = {"code": 0, "data": {"collectionName": "c", "fields": [
    {"name": "id", "type": "Int64", "primaryKey": True},
    {"name": "text", "type": "VarChar"},
    {"name": "vector", "type": "FloatVector"}]}}


def rows(n, with_vec=True):
    return [{"id": i, "text": "t" * 200, **({"vector": VEC} if with_vec else {})} for i in range(n)]


class TestBudgetHelpers:
    def test_vector_detection(self):
        assert budget.is_vector_value(VEC)
        assert not budget.is_vector_value([1, 2, 3])
        assert not budget.is_vector_value(["a"] * 64)
        assert not budget.is_vector_value([True] * 64)
        assert budget.is_vector_value({str(i): 0.5 for i in range(40)})
        assert budget.vector_keys(rows(2)) == ["vector"]

    def test_scalar_fields(self):
        assert budget.scalar_fields(SCHEMA["data"]) == ["id", "text"]
        dyn = {**SCHEMA["data"], "enableDynamicField": True}
        assert budget.scalar_fields(dyn) == ["id", "text", "$meta"]
        assert budget.scalar_fields({"fields": [{"name": "id", "type": "Int64"}]}) is None
        assert budget.scalar_fields({}) is None

    def test_fit_rows_noop_when_small(self):
        r = rows(3, with_vec=False)
        assert budget.fit_rows(r) == (r, None)

    def test_fit_rows_trims_to_budget(self):
        r = rows(100)
        kept, info = budget.fit_rows(r)
        assert len(json.dumps(kept)) <= budget.RESULT_BUDGET
        assert 0 < info["returned"] == len(kept) < 100
        assert info["total"] == 100 and info["vector_keys"] == ["vector"]
        assert kept == r[:len(kept)]  # rows are not altered

    def test_fit_rows_shrinks_single_huge_row(self):
        r = [{"id": 1, "text": "x" * 80_000, "vector": VEC}]
        kept, info = budget.fit_rows(r)
        assert info["shrunk"] and len(kept) == 1
        assert kept[0]["vector"] == "<1024-dim vector omitted>"
        assert len(kept[0]["text"]) < 2_100

    def test_leaner_fields(self):
        assert budget.leaner_fields(rows(2), None) == ["id", "text"]
        assert budget.leaner_fields(rows(2), ["*"]) == ["id", "text"]
        assert budget.leaner_fields(rows(2), ["text", "vector"]) == ["text"]
        assert budget.leaner_fields(rows(2, with_vec=False), None) is None


@pytest.mark.asyncio
class TestToolsWithBudget:
    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_query_excludes_vectors_by_default(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import query
        mock_client.data_plane_api_request.side_effect = [SCHEMA, {"code": 0, "data": rows(3, with_vec=False)}]
        out = json.loads(await query("c1", "r1", "c", filter="id >= 0"))
        body = mock_client.data_plane_api_request.call_args_list[1].kwargs["body_map"]
        assert body["outputFields"] == ["id", "text"]
        assert "vector" in out["notes"][0] and "omitted by default" in out["notes"][0]
        assert len(out["data"]) == 3

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_query_explicit_fields_untouched(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import query
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": rows(2)}
        out = json.loads(await query("c1", "r1", "c", filter="id >= 0", output_fields=["vector"]))
        mock_client.data_plane_api_request.assert_called_once()
        assert mock_client.data_plane_api_request.call_args.kwargs["body_map"]["outputFields"] == ["vector"]
        assert out["data"][0]["vector"] == VEC  # explicitly requested and within budget

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_query_describe_failure_falls_back(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import query
        mock_client.data_plane_api_request.side_effect = [RuntimeError("boom"), {"code": 0, "data": rows(1, False)}]
        out = json.loads(await query("c1", "r1", "c", filter="id >= 0"))
        assert "outputFields" not in mock_client.data_plane_api_request.call_args.kwargs["body_map"]
        assert len(out["data"]) == 1

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_query_star_over_budget_is_trimmed_with_steps(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import query
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": rows(100)}
        raw = await query("c1", "r1", "c", filter="id >= 0", output_fields=["*"], limit=100)
        out = json.loads(raw)
        assert len(raw) < budget.RESULT_BUDGET + 3_000
        n = len(out["data"])
        assert 0 < n < 100
        assert list(out)[:2] == ["notes", "next_steps"]
        assert f"showing {n} of 100 rows" in out["notes"][0] and "vector" in out["notes"][0]
        lean = out["next_steps"][0]
        assert lean["tool"] == "query" and lean["args"]["output_fields"] == ["id", "text"]
        assert lean["args"]["offset"] == 0 and lean["args"]["limit"] == 100

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_query_trim_without_vectors_pages(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import query
        big = [{"id": i, "text": "w" * 3_000} for i in range(100)]
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": big}
        out = json.loads(await query("c1", "r1", "c", filter="id >= 0", output_fields=["text"], limit=100))
        n = len(out["data"])
        rest = out["next_steps"][0]
        assert rest["args"]["offset"] == n and rest["args"]["limit"] == 100 - n
        assert rest["args"]["output_fields"] == ["text"]

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_search_over_budget(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import search
        hits = [{**r, "distance": 0.9} for r in rows(50)]
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": hits}
        out = json.loads(await search("c1", "r1", "c", data=[VEC], anns_field="vector", limit=50,
                                      output_fields=["*"]))
        assert len(out["data"]) < 50
        step = out["next_steps"][0]
        assert step["tool"] == "search" and step["args"]["output_fields"] == ["id", "text"]
        assert step["args"]["data"] == "<same query vectors>"

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_search_small_result_unchanged(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import search
        hits = [{"id": i, "distance": 0.5} for i in range(10)]
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": hits}
        out = json.loads(await search("c1", "r1", "c", data=[VEC], anns_field="vector"))
        assert out["data"] == hits
        assert not any("trimmed" in n for n in out.get("notes", []))

    @patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
    async def test_hybrid_search_over_budget(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import hybrid_search
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": rows(40)}
        out = json.loads(await hybrid_search("c1", "r1", "c", search_requests=[{"data": [VEC]}],
                                             rerank_strategy="rrf", rerank_params={"k": 10}, limit=40,
                                             output_fields=["*"]))
        assert len(out["data"]) < 40 and "trimmed" in out["notes"][0]
        assert out["next_steps"][0]["args"]["output_fields"] == ["id", "text"]
        assert all("offset" not in s["args"] for s in out["next_steps"] if s["tool"] == "hybrid_search")
