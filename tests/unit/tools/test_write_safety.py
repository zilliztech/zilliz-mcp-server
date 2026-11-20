"""Write safety: read-only mode, tool annotations, and two-step confirmation."""

import asyncio
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from zilliz_mcp_server.common.hints import StructuredToolError

WRITE_TOOLS = {"create_free_cluster", "suspend_cluster", "resume_cluster",
               "create_collection", "insert_entities", "delete_entities"}
DESTRUCTIVE = {"suspend_cluster", "delete_entities"}

LIST_TOOLS = """
import asyncio, json
from zilliz_mcp_server.app import zilliz_mcp
from zilliz_mcp_server.tools.zilliz import zilliz_tools
from zilliz_mcp_server.tools.milvus import milvus_tools
tools = asyncio.run(zilliz_mcp.list_tools())
print(json.dumps({t.name: t.annotations.model_dump(exclude_none=True) for t in tools}))
"""


def _registered_tools(read_only: str) -> dict:
    # config is read at import time, so each mode needs a fresh interpreter.
    env = dict(os.environ, ZILLIZ_CLOUD_TOKEN="dummy", ZILLIZ_MCP_READ_ONLY=read_only)
    out = subprocess.run([sys.executable, "-c", LIST_TOOLS], env=env, capture_output=True,
                         text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


class TestReadOnlyMode:
    def test_default_registers_write_tools_with_annotations(self):
        tools = _registered_tools("")
        assert WRITE_TOOLS <= set(tools)
        for name, ann in tools.items():
            if name in WRITE_TOOLS:
                assert ann["readOnlyHint"] is False
                assert ann["destructiveHint"] is (name in DESTRUCTIVE)
            else:
                assert ann["readOnlyHint"] is True and ann["destructiveHint"] is False

    @pytest.mark.parametrize("value", ["true", "1", "TRUE", "yes"])
    def test_read_only_hides_write_tools(self, value):
        tools = _registered_tools(value)
        assert not WRITE_TOOLS & set(tools)
        assert {"list_clusters", "describe_cluster", "search", "query"} <= set(tools)
        assert all(ann["readOnlyHint"] is True for ann in tools.values())

    def test_false_keeps_write_tools(self):
        assert WRITE_TOOLS <= set(_registered_tools("false"))


def _envelope(out: str) -> dict:
    return json.loads(out)


@patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
class TestSuspendConfirm:
    def test_without_confirm_previews_and_does_not_suspend(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import suspend_cluster
        mock_client.control_plane_api_request.return_value = {"code": 0, "data": {
            "clusterId": "in01-x", "clusterName": "prod", "status": "RUNNING", "plan": "Enterprise",
            "cuSize": 4, "regionId": "aws-us-west-2"}}
        env = _envelope(asyncio.run(suspend_cluster("in01-x")))
        mock_client.control_plane_api_request.assert_called_once_with("/v2/clusters/in01-x", method="GET")
        data = env["data"]
        assert data["confirm_required"] is True
        assert data["cluster"]["cluster_name"] == "prod" and data["cluster"]["status"] == "RUNNING"
        assert "reads, writes and searches fail" in data["impact"]
        # No executable next step: following hints must not skip the user's confirmation.
        assert "next_steps" not in env
        assert "confirm=true" in data["how_to_confirm"] and "explicitly agree" in data["how_to_confirm"]

    def test_confirm_true_suspends(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import suspend_cluster
        mock_client.control_plane_api_request.return_value = {"code": 0, "data": {"clusterId": "in01-x"}}
        asyncio.run(suspend_cluster("in01-x", confirm=True))
        mock_client.control_plane_api_request.assert_called_once_with("/v2/clusters/in01-x/suspend", method="POST")


@patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client')
class TestDeleteConfirm:
    ARGS = dict(cluster_id="in01-x", region_id="aws-us-west-2", collection_name="docs", filter="id in [1, 2]")

    def test_without_confirm_counts_and_does_not_delete(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import delete_entities
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": [{"count(*)": 2}]}
        env = _envelope(asyncio.run(delete_entities(**self.ARGS)))
        call = mock_client.data_plane_api_request.call_args.kwargs
        assert call["uri"] == "/v2/vectordb/entities/query"
        assert call["body_map"]["outputFields"] == ["count(*)"] and call["body_map"]["filter"] == "id in [1, 2]"
        assert mock_client.data_plane_api_request.call_count == 1
        assert env["data"]["matching_entities"] == 2 and env["data"]["confirm_required"] is True
        assert "next_steps" not in env
        assert "confirm=true" in env["data"]["how_to_confirm"]

    def test_preview_survives_count_failure(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import delete_entities
        mock_client.data_plane_api_request.side_effect = Exception("collection not loaded")
        data = _envelope(asyncio.run(delete_entities(**self.ARGS)))["data"]
        assert data["matching_entities"] is None and "not loaded" in data["count_error"]

    def test_empty_filter_rejected_before_any_call(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import delete_entities
        with pytest.raises(StructuredToolError, match="filter is required"):
            asyncio.run(delete_entities(**{**self.ARGS, "filter": "  "}, confirm=True))
        mock_client.data_plane_api_request.assert_not_called()

    def test_confirm_true_deletes(self, mock_client):
        from zilliz_mcp_server.tools.milvus.milvus_tools import delete_entities
        mock_client.data_plane_api_request.return_value = {"code": 0, "data": {}}
        asyncio.run(delete_entities(**self.ARGS, confirm=True))
        assert mock_client.data_plane_api_request.call_args.kwargs["uri"] == "/v2/vectordb/entities/delete"


@patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
class TestSuspendAlreadySuspended:
    @pytest.mark.parametrize("status", ["SUSPENDED", "SUSPENDING"])
    def test_preview_says_no_confirmation_needed(self, mock_client, status):
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import suspend_cluster
        mock_client.control_plane_api_request.return_value = {"code": 0, "data": {"clusterId": "in01-x", "status": status}}
        env = _envelope(asyncio.run(suspend_cluster("in01-x")))
        assert env["data"]["confirm_required"] is False and status in env["data"]["message"]
        assert env["next_steps"][0]["tool"] == "describe_cluster"
        mock_client.control_plane_api_request.assert_called_once_with("/v2/clusters/in01-x", method="GET")


class TestConfirmThroughMcp:
    """confirm goes through the MCP argument model, which must not coerce strings or ints to True."""

    def _call(self, name, args):
        from zilliz_mcp_server.app import zilliz_mcp
        from zilliz_mcp_server.tools.zilliz import zilliz_tools  # noqa: F401  (registers tools)
        from zilliz_mcp_server.tools.milvus import milvus_tools  # noqa: F401
        return asyncio.run(zilliz_mcp.call_tool(name, args))

    @pytest.mark.parametrize("value", ["yes", "1", 1, "True ", "true"])
    def test_non_boolean_confirm_rejected_before_any_request(self, value):
        with patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client') as cp, \
             patch('zilliz_mcp_server.tools.milvus.milvus_tools.openapi_client') as dp:
            with pytest.raises(Exception, match="confirm"):
                self._call("suspend_cluster", {"cluster_id": "in01-x", "confirm": value})
            with pytest.raises(Exception, match="confirm"):
                self._call("delete_entities", {**TestDeleteConfirm.ARGS, "confirm": value})
            cp.control_plane_api_request.assert_not_called()
            dp.data_plane_api_request.assert_not_called()

    def test_boolean_true_executes(self):
        with patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client') as cp:
            cp.control_plane_api_request.return_value = {"code": 0, "data": {"clusterId": "in01-x"}}
            self._call("suspend_cluster", {"cluster_id": "in01-x", "confirm": True})
            cp.control_plane_api_request.assert_called_once_with("/v2/clusters/in01-x/suspend", method="POST")

    def test_omitted_confirm_previews(self):
        with patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client') as cp:
            cp.control_plane_api_request.return_value = {"code": 0, "data": {"status": "RUNNING"}}
            self._call("suspend_cluster", {"cluster_id": "in01-x"})
            assert cp.control_plane_api_request.call_args.kwargs["method"] == "GET"
