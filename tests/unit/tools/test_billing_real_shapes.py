"""Billing tools against response shapes observed on a real organization (all ids and amounts synthetic).

Observed shapes: usage/query items carry all nine property keys, most null; amounts are float
USD with amount == quantity * price.unitPrice; one org-wide day is ~85 KB of JSON (~400 items).
List Invoices needs both pageSize and currentPage, otherwise code 20011.
"""

import asyncio
import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from zilliz_mcp_server.common.hints import StructuredToolError, ZillizAPIError
from zilliz_mcp_server.tools.zilliz import billing_tools

PROPS = ["projectId", "regionId", "cuType", "plan", "clusterId", "resourceType", "resourceId",
         "volumeName", "requestClass"]


def _call(tool, **kwargs):
    return asyncio.run(getattr(billing_tools, tool)(**kwargs))


def _real_item(i, cost_type="backup", unit="GB"):
    props = dict.fromkeys(PROPS)
    props.update(projectId=f"proj-{i % 40}", regionId="aws-us-west-2",
                 clusterId=f"in01-{i:015d}" if i % 10 else None)
    q, p = 1.5 + i, 0.025
    return {"costType": cost_type, "quantity": q, "amount": q * p, "unit": unit,
            "listPrice": {"unitPrice": p}, "price": {"unitPrice": p}, "properties": props}


def _usage(days=2, per_day=400):
    results = []
    for d in range(days):
        items = [_real_item(i, ("backup", "storage", "compute")[i % 3]) for i in range(per_day)]
        day = date(2026, 10, 1) + timedelta(days=d)
        items[0]["amount"] += d  # make daily totals differ so amount order != date order
        results.append({"intervalStart": f"{day}T00:00:00Z",
                        "intervalEnd": f"{day + timedelta(days=1)}T00:00:00Z",
                        "total": sum(it["amount"] for it in items), "currency": "USD", "items": items})
    return {"code": 0, "data": {"results": results}}


@patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
class TestUsageSize:
    def test_daily_without_filter_returns_totals_not_line_items(self, mock_client):
        mock_client.control_plane_api_request.return_value = _usage(days=7)
        out = _call("query_daily_usage", start="2026-11-01", end="2026-11-07")
        days = json.loads(out)["data"]
        assert len(days) == 7
        assert all("items" not in d for d in days)
        assert set(days[0]["by_cost_type"]) == {"backup", "storage", "compute"}
        assert len(out) < 3000  # a 7-day org-wide raw dump is ~600 KB

    def test_daily_with_filter_caps_line_items_and_drops_null_properties(self, mock_client):
        resp = _usage(days=7)
        for b in resp["data"]["results"]:
            for it in b["items"]:
                it["properties"]["projectId"] = "proj-1"
        mock_client.control_plane_api_request.return_value = resp
        out = json.loads(_call("query_daily_usage", start="2026-11-01", end="2026-11-07",
                               project_id="proj-1"))
        days = out["data"]
        shown = sum(len(d.get("items", [])) for d in days)
        assert 0 < shown <= billing_tools.MAX_LINE_ITEMS
        assert sum(d.get("items_truncated", 0) for d in days) == 7 * 400 - shown
        # Size, not only item count, is capped by the shared budget; totals stay for every day.
        assert len(json.dumps(days)) <= billing_tools.RESULT_BUDGET
        assert all("by_cost_type" in d and "total" in d for d in days)
        assert any("items_truncated" in n and "newest days first" in n for n in out.get("notes", []))
        # The newest day keeps its items; the oldest days are the ones cut.
        assert days[-1]["items"] and not days[0]["items"]
        props = days[-1]["items"][0]["properties"]
        assert None not in props.values() and "volumeName" not in props

    def test_daily_with_filter_small_result_untouched(self, mock_client):
        mock_client.control_plane_api_request.return_value = _usage(days=2, per_day=5)
        out = json.loads(_call("query_daily_usage", start="2026-11-01", end="2026-11-02",
                               project_id="proj-1"))
        assert "notes" not in out and all("items_truncated" not in d for d in out["data"])

    def test_summary_limits_groups_and_rolls_up_other(self, mock_client):
        mock_client.control_plane_api_request.return_value = _usage(days=1)
        s = json.loads(_call("get_usage_summary", start="2026-11-01", end="2026-11-01"))["data"]
        assert s["group_count"] == 361  # 360 clusters + unattributed
        assert len(s["groups"]) == billing_tools.DEFAULT_GROUP_LIMIT + 1
        other = s["groups"][-1]
        assert other["key"] == "other" and other["other_group_count"] == 361 - billing_tools.DEFAULT_GROUP_LIMIT
        assert abs(sum(g["amount"] for g in s["groups"]) - s["total"]) < 0.05

    def test_summary_limit_validated(self, mock_client):
        with pytest.raises(StructuredToolError, match="limit must be"):
            _call("get_usage_summary", start="2026-11-01", end="2026-11-01", limit=0)
        mock_client.control_plane_api_request.assert_not_called()

    def test_summary_by_day_returns_every_day_in_date_order(self, mock_client):
        # "How much did we spend each day last month?" must not be cut to the top 20 days.
        mock_client.control_plane_api_request.return_value = _usage(days=31, per_day=30)
        s = json.loads(_call("get_usage_summary", start="2026-10-01", end="2026-10-31",
                             group_by="day"))["data"]
        keys = [g["key"] for g in s["groups"]]
        assert len(keys) == 31 and keys == sorted(keys) and "other" not in keys
        assert keys[0] == "2026-10-01" and keys[-1] == "2026-10-31"

    def test_summary_by_day_long_range_drops_cost_types_with_note(self, mock_client):
        days = billing_tools.LONG_RANGE_DAYS + 1
        mock_client.control_plane_api_request.return_value = _usage(days=days, per_day=30)
        env = json.loads(_call("get_usage_summary", start="2026-10-01",
                               end=str(date(2026, 10, 1) + timedelta(days=days - 1)), group_by="day"))
        groups = env["data"]["groups"]
        assert len(groups) == days
        assert all(set(g) == {"key", "amount"} for g in groups)
        assert "group_by=month" in env["notes"][0]

    def test_summary_by_day_within_long_range_keeps_cost_types(self, mock_client):
        mock_client.control_plane_api_request.return_value = _usage(days=billing_tools.LONG_RANGE_DAYS, per_day=30)
        env = json.loads(_call("get_usage_summary", start="2026-10-01", end="2026-12-31", group_by="day"))
        assert "notes" not in env
        assert all("by_cost_type" in g and "share_percent" not in g for g in env["data"]["groups"])

    def test_summary_by_month_in_date_order_with_cost_types(self, mock_client):
        mock_client.control_plane_api_request.return_value = _usage(days=120, per_day=30)
        s = json.loads(_call("get_usage_summary", start="2026-10-01", end="2027-01-28",
                             group_by="month"))["data"]
        assert [g["key"] for g in s["groups"]] == ["2026-10", "2026-11", "2026-12", "2027-01"]
        assert set(s["groups"][0]["by_cost_type"]) == {"backup", "storage", "compute"}
        assert abs(sum(g["amount"] for g in s["groups"]) - s["total"]) < 0.05

    def test_summary_by_month_notes_partial_edge_months(self, mock_client):
        mock_client.control_plane_api_request.return_value = _usage(days=120, per_day=30)
        env = json.loads(_call("get_usage_summary", start="2026-10-01", end="2027-01-28", group_by="month"))
        assert len(env["notes"]) == 1 and "Partial month(s) 2027-01:" in env["notes"][0]
        mock_client.control_plane_api_request.return_value = _usage(days=92, per_day=30)
        env = json.loads(_call("get_usage_summary", start="2026-10-01", end="2026-12-31", group_by="month"))
        assert "notes" not in env

    def test_daily_without_filter_covers_a_month(self, mock_client):
        mock_client.control_plane_api_request.return_value = _usage(days=31)
        out = _call("query_daily_usage", start="2026-10-01", end="2026-10-31")
        days = json.loads(out)["data"]
        assert [d["day"] for d in days][::30] == ["2026-10-01", "2026-10-31"]
        assert len(out) < 12000


@patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
class TestInvoicesPaging:
    def test_always_sends_both_paging_params(self, mock_client):
        mock_client.control_plane_api_request.return_value = {"code": 0, "data": {"count": 0, "invoices": []}}
        _call("list_invoices")
        params = mock_client.control_plane_api_request.call_args.kwargs["params_map"]
        assert params == {"pageSize": 10, "currentPage": 1}

    @pytest.mark.parametrize("kw", [{"page_size": 0}, {"page_size": 101}, {"current_page": 0}])
    def test_invalid_paging_rejected_locally(self, mock_client, kw):
        with pytest.raises(StructuredToolError) as e:
            _call("list_invoices", **kw)
        assert e.value.payload["error"] == "INVALID_ARGUMENT"
        mock_client.control_plane_api_request.assert_not_called()

    def test_20011_gets_actionable_fix(self, mock_client):
        mock_client.control_plane_api_request.side_effect = ZillizAPIError(
            "An unknown error occurred. Please retry later or contact us.", code=20011)
        with pytest.raises(StructuredToolError) as e:
            _call("list_invoices", page_size=20)
        p = e.value.payload
        assert "20011" in p["fix"] and "Zilliz support" in p["fix"]
        assert p["next_steps"][0]["args"] == {"page_size": 20, "current_page": 1}

    def test_describe_invoice_docs_prefer_list(self, _mock_client):
        assert "prefer" in billing_tools.describe_invoice.__doc__
        assert "server error" not in billing_tools.describe_invoice.__doc__
