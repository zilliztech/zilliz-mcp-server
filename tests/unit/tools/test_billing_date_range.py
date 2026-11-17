"""Usage date range: no local cut-off; the server's bare 'Bad request' and empty early results get hints."""
import asyncio
import json
from unittest.mock import patch

import pytest

from zilliz_mcp_server.common.hints import StructuredToolError, ZillizAPIError
from zilliz_mcp_server.tools.zilliz import billing_tools as bt

MOD = "zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client"


def _err(tool, **kw):
    with pytest.raises(StructuredToolError) as e:
        asyncio.run(getattr(bt, tool)(**kw))
    return e.value.payload


def _ok(tool, **kw):
    return json.loads(asyncio.run(getattr(bt, tool)(**kw)))


@patch(MOD)
def test_early_start_is_sent_to_the_server(mock_client):
    # Other organizations may have older data: the observed boundary is not enforced locally.
    mock_client.control_plane_api_request.return_value = {"code": 0, "data": {"results": [
        {"intervalStart": "2024-01-01T00:00:00Z", "currency": "USD", "total": 1.0,
         "items": [{"costType": "compute", "amount": 1.0, "properties": {}}]}]}}
    out = _ok("query_daily_usage", start="2024-01-01", end="2024-01-31")
    assert mock_client.control_plane_api_request.called
    assert out["data"][0]["total"] == 1.0 and "notes" not in out


@patch(MOD)
def test_server_bad_request_on_early_start_gets_clamped_retry(mock_client):
    mock_client.control_plane_api_request.side_effect = ZillizAPIError("Bad request.", code=3)
    p = _err("get_usage_summary", start="2024-12-01", end="2025-03-31")
    assert p["error"] == "INVALID_ARGUMENT" and p["field"] == "start" and p["got"] == "2024-12-01"
    assert "Observed" in p["message"] and "2025-03-01" in p["message"] and "list_invoices" in p["fix"]
    assert p["next_steps"][0]["tool"] == "get_usage_summary"
    assert p["next_steps"][0]["args"]["start"] == "2025-03-01" and p["next_steps"][0]["args"]["end"] == "2025-03-31"
    assert p["next_steps"][-1]["tool"] == "list_invoices"


@patch(MOD)
def test_server_bad_request_entirely_early_points_to_invoices_only(mock_client):
    mock_client.control_plane_api_request.side_effect = ZillizAPIError("Bad request.", code=3)
    p = _err("query_daily_usage", start="2024-01-01", end="2024-01-31")
    assert [s["tool"] for s in p["next_steps"]] == ["list_invoices"]


@patch(MOD)
def test_server_bad_request_with_later_start_still_gets_hint(mock_client):
    # If the boundary is rolling or differs per org, a later start can be rejected too.
    mock_client.control_plane_api_request.side_effect = ZillizAPIError("Bad request.", code=3)
    p = _err("get_usage_summary", start="2025-04-01", end="2025-04-30")
    assert p["error"] == "INVALID_ARGUMENT" and p["field"] == "start" and p["got"] == "2025-04-01"
    assert "observed" in p["expected"] and "list_invoices" in p["fix"]
    assert [s["tool"] for s in p["next_steps"]] == ["list_invoices"]


@patch(MOD)
def test_other_server_errors_stay_generic(mock_client):
    mock_client.control_plane_api_request.side_effect = ZillizAPIError("internal", code=500)
    p = _err("get_usage_summary", start="2024-04-01", end="2024-04-30")
    assert "list_invoices" not in json.dumps(p.get("next_steps", []))


@pytest.mark.parametrize("tool", ["get_usage_summary", "query_daily_usage"])
@patch(MOD)
def test_empty_early_result_says_empty_is_not_zero(mock_client, tool):
    mock_client.control_plane_api_request.return_value = {"code": 0, "data": {"results": [
        {"intervalStart": "2022-06-01T00:00:00Z", "currency": "USD", "total": 0, "items": []}]}}
    out = _ok(tool, start="2022-06-01", end="2022-06-07")
    assert any("empty does not mean zero spend" in n for n in out["notes"])


@patch(MOD)
def test_empty_result_after_boundary_has_no_note(mock_client):
    mock_client.control_plane_api_request.return_value = {"code": 0, "data": {"results": [
        {"intervalStart": "2025-03-01T00:00:00Z", "currency": "USD", "total": 0, "items": []}]}}
    out = _ok("query_daily_usage", start="2025-03-01", end="2025-03-02")
    assert "notes" not in out
