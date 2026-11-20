"""
Unit tests for zilliz_mcp_server.tools.zilliz.billing_tools module.

Tests billing operations like usage queries and invoices.
"""

import json
import pytest
from unittest.mock import patch

# Enable asyncio for all async tests in this module
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def mock_zilliz_mcp():
    """Mock the zilliz_mcp app for testing."""
    with patch('zilliz_mcp_server.tools.zilliz.billing_tools.zilliz_mcp') as mock_app:
        mock_app.tool.return_value = lambda func: func  # Return function unchanged
        yield mock_app


def _item(cost_type, amount, cluster_id="in01-a", project_id="proj-1", region_id="aws-us-west-2"):
    return {
        "costType": cost_type,
        "properties": {
            "projectId": project_id,
            "regionId": region_id,
            "cuType": "Performance-optimized",
            "plan": "Enterprise",
            "clusterId": cluster_id,
        },
        "quantity": 1.0,
        "unit": "cu_hour",
        "listPrice": {"unitPrice": amount},
        "price": {"unitPrice": amount},
        "amount": amount,
    }


def _bucket(day, items):
    return {
        "intervalStart": f"{day}T00:00:00Z",
        "intervalEnd": f"{day}T23:59:59Z",
        "total": sum(i["amount"] for i in items),
        "currency": "USD",
        "items": items,
    }


@pytest.fixture
def usage_response():
    """Two daily buckets across two clusters and two projects."""
    return {
        "code": 0,
        "data": {
            "results": [
                _bucket("2026-09-16", [
                    _item("compute", 10.1234567891, "in01-a", "proj-1"),
                    _item("storage", 0.5, "in01-a", "proj-1"),
                    _item("compute", 3.0, "in01-b", "proj-2", "gcp-us-west1"),
                ]),
                _bucket("2026-09-17", [
                    _item("compute", 10.0, "in01-a", "proj-1"),
                    _item("lakebase_storage", 1.25, "in01-b", "proj-2", "gcp-us-west1"),
                ]),
            ]
        },
    }


class TestQueryDates:
    """Date handling shared by the usage tools."""

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_dates_sent_as_midnight_utc_rfc3339(self, mock_client, usage_response):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        mock_client.control_plane_api_request.return_value = usage_response

        await get_usage_summary("2026-09-16", "2026-09-17")

        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/usage/query",
            body_map={"start": "2026-09-16T00:00:00Z", "end": "2026-09-17T00:00:00Z"},
            method="POST",
        )

    @pytest.mark.parametrize("start,end", [
        ("2026-09-16T00:00:00Z", "2026-09-17"),
        ("16/09/2026", "2026-09-17"),
        ("2026-09-18", "2026-09-17"),
    ])
    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_invalid_dates_rejected(self, mock_client, start, end):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        with pytest.raises(Exception):
            await get_usage_summary(start, end)
        mock_client.control_plane_api_request.assert_not_called()

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_summary_range_cap(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        with pytest.raises(Exception, match="366"):
            await get_usage_summary("2025-01-01", "2026-09-17")
        mock_client.control_plane_api_request.assert_not_called()


class TestGetUsageSummary:
    """Test cases for get_usage_summary function."""

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_group_by_cluster(self, mock_client, usage_response):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        mock_client.control_plane_api_request.return_value = usage_response

        result = json.loads(await get_usage_summary("2026-09-16", "2026-09-17"))

        assert result["currency"] == "USD"
        assert result["group_by"] == "cluster"
        assert result["total"] == 24.87
        groups = result["groups"]
        assert [g["key"] for g in groups] == ["in01-a", "in01-b"]
        assert groups[0]["amount"] == 20.62
        assert groups[0]["share_percent"] == 82.9
        assert groups[0]["by_cost_type"] == {"compute": 20.12, "storage": 0.5}
        assert groups[1]["by_cost_type"] == {"compute": 3.0, "lakebase_storage": 1.25}

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_rounds_only_at_the_end(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        # Each 0.004 rounds to 0.00 on its own; the sum 0.012 must round to 0.01.
        mock_client.control_plane_api_request.return_value = {
            "code": 0,
            "data": {"results": [_bucket("2026-09-16", [_item("compute", 0.004)] * 3)]},
        }

        result = json.loads(await get_usage_summary("2026-09-16", "2026-09-16"))

        assert result["total"] == 0.01

    @pytest.mark.parametrize("group_by,expected_keys", [
        ("project", ["proj-1", "proj-2"]),
        ("cost_type", ["compute", "lakebase_storage", "storage"]),
        ("region", ["aws-us-west-2", "gcp-us-west1"]),
        ("day", ["2026-09-16", "2026-09-17"]),
    ])
    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_group_by_options(self, mock_client, usage_response, group_by, expected_keys):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        mock_client.control_plane_api_request.return_value = usage_response

        result = json.loads(await get_usage_summary("2026-09-16", "2026-09-17", group_by=group_by))

        assert sorted(g["key"] for g in result["groups"]) == expected_keys

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_group_by_cost_type_omits_breakdown(self, mock_client, usage_response):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        mock_client.control_plane_api_request.return_value = usage_response

        result = json.loads(await get_usage_summary("2026-09-16", "2026-09-17", group_by="cost_type"))

        assert all("by_cost_type" not in g for g in result["groups"])

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_invalid_group_by(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        with pytest.raises(Exception, match="group_by"):
            await get_usage_summary("2026-09-16", "2026-09-17", group_by="plan")
        mock_client.control_plane_api_request.assert_not_called()

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_filter_by_cluster(self, mock_client, usage_response):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        mock_client.control_plane_api_request.return_value = usage_response

        result = json.loads(await get_usage_summary(
            "2026-09-16", "2026-09-17", group_by="cost_type", cluster_id="in01-b"))

        assert result["total"] == 4.25
        assert {g["key"]: g["amount"] for g in result["groups"]} == {"compute": 3.0, "lakebase_storage": 1.25}

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_filter_by_project(self, mock_client, usage_response):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        mock_client.control_plane_api_request.return_value = usage_response

        result = json.loads(await get_usage_summary("2026-09-16", "2026-09-17", project_id="proj-1"))

        assert result["total"] == 20.62
        assert [g["key"] for g in result["groups"]] == ["in01-a"]

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_items_without_cluster_grouped_as_unattributed(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        item = _item("audit_log_cu", 2.0)
        del item["properties"]["clusterId"]
        mock_client.control_plane_api_request.return_value = {
            "code": 0, "data": {"results": [_bucket("2026-09-16", [item])]},
        }

        result = json.loads(await get_usage_summary("2026-09-16", "2026-09-16"))

        assert result["groups"][0]["key"] == "unattributed"

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_empty_results(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        mock_client.control_plane_api_request.return_value = {"code": 0, "data": {"results": []}}

        result = json.loads(await get_usage_summary("2026-09-16", "2026-09-17"))

        assert result["total"] == 0
        assert result["groups"] == []

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_api_error(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import get_usage_summary

        mock_client.control_plane_api_request.side_effect = Exception("Business error: permission denied")

        with pytest.raises(Exception, match="Failed to get usage summary"):
            await get_usage_summary("2026-09-16", "2026-09-17")


class TestQueryDailyUsage:
    """Test cases for query_daily_usage function."""

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_returns_daily_buckets(self, mock_client, usage_response):
        from zilliz_mcp_server.tools.zilliz.billing_tools import query_daily_usage

        mock_client.control_plane_api_request.return_value = usage_response

        result = json.loads(await query_daily_usage("2026-09-16", "2026-09-17"))

        assert [d["day"] for d in result] == ["2026-09-16", "2026-09-17"]
        assert result[0]["currency"] == "USD"
        assert len(result[0]["items"]) == 3
        assert result[0]["items"][0]["cost_type"] == "compute"
        assert result[0]["items"][0]["properties"]["clusterId"] == "in01-a"

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_filter_recomputes_day_total(self, mock_client, usage_response):
        from zilliz_mcp_server.tools.zilliz.billing_tools import query_daily_usage

        mock_client.control_plane_api_request.return_value = usage_response

        result = json.loads(await query_daily_usage("2026-09-16", "2026-09-17", cluster_id="in01-a"))

        assert result[0]["total"] == 10.6234567891
        assert all(i["properties"]["clusterId"] == "in01-a" for d in result for i in d["items"])

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_range_cap(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import query_daily_usage

        with pytest.raises(Exception, match="7 days"):
            await query_daily_usage("2026-09-10", "2026-09-17")
        mock_client.control_plane_api_request.assert_not_called()


class TestInvoices:
    """Test cases for list_invoices and describe_invoice functions."""

    INVOICE = {
        "id": "inv-123",
        "orgId": "org-1",
        "periodStart": "2026-08-01T00:00:00Z",
        "periodEnd": "2026-08-31T23:59:59Z",
        "invoiceDate": "2026-09-01T00:00:00Z",
        "dueDate": "2026-09-15T00:00:00Z",
        "currency": "USD",
        "status": "paid",
        "usageAmount": 100.5,
        "creditsApplied": 10.0,
        "alreadyBilledAmount": 0,
        "subtotal": 90.5,
        "tax": 0,
        "total": 90.5,
        "advancePayAmount": 0,
        "amountDue": 0,
    }

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_list_invoices(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import list_invoices

        mock_client.control_plane_api_request.return_value = {
            "code": 0,
            "data": {"count": 1, "currentPage": 1, "pageSize": 10, "invoices": [self.INVOICE]},
        }

        result = json.loads(await list_invoices())

        mock_client.control_plane_api_request.assert_called_once_with(
            "/v2/invoices", params_map={"pageSize": 10, "currentPage": 1})
        assert result["count"] == 1
        invoice = result["invoices"][0]
        assert invoice["invoice_id"] == "inv-123"
        assert invoice["status"] == "paid"
        assert invoice["usage_amount"] == 100.5
        assert invoice["amount_due"] == 0

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_describe_invoice(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import describe_invoice

        mock_client.control_plane_api_request.return_value = {"code": 0, "data": self.INVOICE}

        result = json.loads(await describe_invoice("inv-123"))

        mock_client.control_plane_api_request.assert_called_once_with("/v2/invoices/inv-123", method="GET")
        assert result["invoice_id"] == "inv-123"
        assert result["period_start"] == "2026-08-01T00:00:00Z"
        assert result["credits_applied"] == 10.0

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    async def test_describe_invoice_error(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.billing_tools import describe_invoice

        mock_client.control_plane_api_request.side_effect = Exception("Business error: not found")

        with pytest.raises(Exception, match="Failed to describe invoice"):
            await describe_invoice("inv-missing")
