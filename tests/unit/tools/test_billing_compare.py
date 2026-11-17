"""Unit tests for compare_billing_periods (mocked; response shapes follow the public
usage/query and list-invoices docs). Amount units are not asserted as currency units."""
import json
from unittest.mock import patch

import pytest

from zilliz_mcp_server.common.hints import StructuredToolError

MOD = "zilliz_mcp_server.tools.zilliz.billing_compare"


def _item(cluster, cost, qty, amount, unit="hour"):
    return {"costType": cost, "quantity": qty, "unit": unit, "amount": amount,
            "properties": {"clusterId": cluster, "projectId": "proj-1", "regionId": "aws-us-west-2"}}


def _usage(*items, currency="USD"):
    return {"code": 0, "data": {"results": [{"intervalStart": "2026-09-01T00:00:00Z",
                                             "currency": currency, "items": list(items)}]}}


INVOICES = {"code": 0, "data": {"count": 2, "invoices": [
    {"id": "inv-10", "periodStart": "2026-10-01T00:00:00Z", "periodEnd": "2026-10-31T23:59:59Z",
     "status": "unpaid", "usageAmount": 1200, "creditsApplied": 0, "total": 1200},
    {"id": "inv-09", "periodStart": "2026-09-01T00:00:00Z", "periodEnd": "2026-09-30T23:59:59Z",
     "status": "paid", "usageAmount": 800, "creditsApplied": 0, "total": 800},
]}}


def _client(base, target, invoices=INVOICES):
    def fake(uri, params_map=None, body_map=None, method="GET"):
        if uri == "/v2/invoices":
            if isinstance(invoices, Exception):
                raise invoices
            return invoices
        return base if body_map["start"].startswith("2026-09") else target
    return fake


async def _run(**kw):
    from zilliz_mcp_server.tools.zilliz.billing_compare import compare_billing_periods
    args = dict(base_start="2026-09-01", base_end="2026-09-30", target_start="2026-10-01", target_end="2026-10-31")
    args.update(kw)
    return json.loads(await compare_billing_periods(**args))


@pytest.mark.asyncio
async def test_quantity_driver_new_gone_and_hints():
    base = _usage(_item("in01-a", "compute", 1000, 500), _item("in01-a", "storage", 100, 50),
                  _item("in01-old", "compute", 100, 250))
    target = _usage(_item("in01-a", "compute", 2000, 1000), _item("in01-a", "storage", 100, 50),
                    _item("in01-new", "storage", 10, 150))
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, target)):
        out = await _run()
    d = out["data"]
    assert d["base"]["usage_total"] == 800.0 and d["target"]["usage_total"] == 1200.0
    assert d["change"]["pct"] == 50.0
    assert d["base"]["days"] == 30 and d["target"]["days"] == 31
    top = d["top_changes"][0]
    assert top["key"] == "in01-a / compute" and top["driver"] == "quantity"
    assert top["quantity_effect"] == 500.0 and top["price_effect"] == 0.0
    assert top["share_of_change_pct"] == 125.0
    assert d["new_keys"] == ["in01-new / storage"] and d["gone_keys"] == ["in01-old / compute"]
    flat = next(r for r in d["top_changes"] if r["key"] == "in01-a / storage")
    assert flat["driver"] == "flat"
    assert d["invoice_view"]["base"]["invoice_id"] == "inv-09"
    assert d["invoice_view"]["target"]["invoice_id"] == "inv-10"
    steps = out["next_steps"]
    assert steps[0]["tool"] == "query_daily_usage"
    # query_daily_usage now accepts up to 31 days, so the whole target month fits in one call.
    assert steps[0]["args"] == {"start": "2026-10-01", "end": "2026-10-31", "cluster_id": "in01-a"}
    assert steps[1]["tool"] == "describe_cluster"
    assert any("daily_avg_pct" in n for n in out["notes"])


@pytest.mark.asyncio
async def test_price_driver_and_effects_sum_to_change():
    base = _usage(_item("in01-a", "compute", 1000, 500))
    target = _usage(_item("in01-a", "compute", 1000, 650))
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, target)):
        out = await _run(target_end="2026-10-30")
    row = out["data"]["top_changes"][0]
    assert row["driver"] == "price" and row["unit_price_pct"] == 30.0
    assert row["quantity_effect"] + row["price_effect"] == row["abs"] == 150.0
    assert "notes" not in out or not any("differ in length" in n for n in out["notes"])


@pytest.mark.asyncio
async def test_invoices_unavailable_still_returns_usage_comparison():
    base = _usage(_item("in01-a", "compute", 1, 1))
    target = _usage(_item("in01-a", "compute", 2, 2))
    with patch(f"{MOD}.openapi_client.control_plane_api_request",
               side_effect=_client(base, target, invoices=Exception("boom"))):
        out = await _run()
    assert "invoice_view" not in out["data"]
    assert any("Invoices unavailable" in n for n in out["notes"])


@pytest.mark.asyncio
async def test_multiple_currencies_rejected():
    base = _usage(_item("in01-a", "compute", 1, 1), currency="USD")
    target = _usage(_item("in01-a", "compute", 1, 1), currency="EUR")
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, target)):
        with pytest.raises(StructuredToolError) as ei:
            await _run()
    p = ei.value.payload
    assert p["error"] == "INVALID_ARGUMENT" and "currencies" in p["message"]


@pytest.mark.asyncio
async def test_bad_group_by_and_dates_are_invalid_argument():
    with pytest.raises(StructuredToolError) as ei:
        await _run(group_by="day")
    assert "INVALID_ARGUMENT" in str(ei.value) and "cluster_cost_type" in str(ei.value)
    with pytest.raises(StructuredToolError):
        await _run(base_start="2026/09/01")


@pytest.mark.asyncio
async def test_base_bad_request_gets_actionable_error():
    from zilliz_mcp_server.common.openapi_client import ZillizAPIError
    def fake(uri, params_map=None, body_map=None, method="GET"):
        if body_map and body_map["start"].startswith("2024"):
            raise ZillizAPIError("Bad request.", code=3)
        return _usage()
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=fake) as m:
        with pytest.raises(StructuredToolError) as ei:
            await _run(base_start="2024-09-01", base_end="2024-09-30")
    p = ei.value.payload
    assert m.called  # no local cut-off: the server decides
    assert p["error"] == "INVALID_ARGUMENT" and p["field"] == "base_start" and "2025-03-01" in p["fix"]
    assert [s["tool"] for s in p["next_steps"]] == ["list_invoices"]


@pytest.mark.asyncio
async def test_empty_early_base_is_not_read_as_zero_spend():
    def fake(uri, params_map=None, body_map=None, method="GET"):
        if uri == "/v2/invoices":
            return INVOICES
        return _usage() if body_map["start"].startswith("2022") else _usage(_item("in01-a", "compute", 10, 50))
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=fake):
        out = await _run(base_start="2022-09-01", base_end="2022-09-30")
    assert out["notes"][0].startswith("base period:") and "empty does not mean zero spend" in out["notes"][0]


@pytest.mark.asyncio
async def test_permission_denied_gives_actionable_error():
    from zilliz_mcp_server.common.openapi_client import ZillizAPIError
    err = ZillizAPIError("Missing ACL permission: orgId=org-x, resource=billing, action=view", code=96041) \
        if "code" in ZillizAPIError.__init__.__code__.co_varnames else ZillizAPIError(
            "Missing ACL permission: orgId=org-x, resource=billing, action=view")
    if getattr(err, "code", None) is None:
        err.code = 96041
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=err):
        with pytest.raises(StructuredToolError) as ei:
            await _run()
    p = ei.value.payload
    assert p["error"] == "PERMISSION_DENIED"
    assert p["missing_permission"] == "billing:view"
    for k in ("who_can_grant", "fix", "message_for_admin", "next_steps"):
        assert p.get(k), k
    assert p["next_steps"][0]["tool"] == "compare_billing_periods"
    assert p["next_steps"][0]["args"]["base_start"] == "2026-09-01"


@pytest.mark.asyncio
async def test_top_n_bounded():
    for bad in (0, 51):
        with pytest.raises(StructuredToolError) as ei:
            await _run(top_n=bad)
        assert ei.value.payload["error"] == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_cost_type_group_does_not_point_at_an_arbitrary_cluster():
    base = _usage(_item("in01-a", "compute", 100, 100), _item("in01-b", "compute", 100, 100))
    target = _usage(_item("in01-a", "compute", 300, 300), _item("in01-b", "compute", 100, 100))
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, target)):
        out = await _run(group_by="cost_type")
    assert [s["tool"] for s in out["next_steps"]] == ["query_daily_usage"]
    assert "cluster_id" not in out["next_steps"][0]["args"]


@pytest.mark.asyncio
async def test_project_group_mixed_units_has_no_price_split_and_scopes_by_project():
    base = _usage(_item("in01-a", "compute", 100, 100), _item("in01-a", "storage", 10, 5, unit="GB"))
    target = _usage(_item("in01-a", "compute", 200, 200), _item("in01-a", "storage", 10, 5, unit="GB"))
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, target)):
        out = await _run(group_by="project")
    row = out["data"]["top_changes"][0]
    assert row["driver"] == "unknown" and "price_effect" not in row
    assert out["next_steps"][0]["args"]["project_id"] == "proj-1"


@pytest.mark.asyncio
async def test_new_and_gone_lists_capped_with_counts():
    base = _usage(*[_item(f"in01-g{i:02d}", "compute", 1, i + 1) for i in range(25)])
    target = _usage(*[_item(f"in01-n{i:02d}", "compute", 1, i + 1) for i in range(25)])
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, target)):
        out = await _run(top_n=50)
    d = out["data"]
    assert len(d["new_keys"]) == 20 and d["new_key_count"] == 25 and d["gone_key_count"] == 25
    assert d["new_keys"][0] == "in01-n24 / compute"  # largest first


@pytest.mark.asyncio
async def test_period_spanning_several_invoices_sums_them():
    base = _usage(_item("in01-a", "compute", 1, 1))
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, base)):
        out = await _run(base_start="2026-08-01", base_end="2026-09-30")
    v = out["data"]["invoice_view"]
    assert v["base"]["invoice_id"] == "inv-09" and "invoices" not in v["base"]
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, base)):
        out = await _run(target_start="2026-09-01", target_end="2026-10-31")
    t = out["data"]["invoice_view"]["target"]
    assert t["invoices"] == 2 and t["usage_amount"] == 2000.0 and t["statuses"] == ["paid", "unpaid"]


def _inv(i, start, end, amount=100):
    return {"id": f"inv-{i}", "periodStart": f"{start}T00:00:00Z", "periodEnd": f"{end}T23:59:59Z",
            "status": "paid", "usageAmount": amount, "creditsApplied": 0, "total": amount}


@pytest.mark.asyncio
async def test_invoices_are_paged_until_count_reached():
    from zilliz_mcp_server.tools.zilliz import billing_compare as bc
    base = _usage(_item("in01-a", "compute", 1, 1))
    pages = {1: [_inv(n, "2027-01-01", "2027-01-31") for n in range(bc.INVOICE_PAGE_SIZE)],
             2: [_inv("09", "2026-09-01", "2026-09-30", 800)]}
    seen = []

    def fake(uri, params_map=None, body_map=None, method="GET"):
        if uri == "/v2/invoices":
            seen.append(params_map["currentPage"])
            return {"code": 0, "data": {"count": bc.INVOICE_PAGE_SIZE + 1,
                                        "invoices": pages.get(params_map["currentPage"], [])}}
        return base
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=fake):
        out = await _run()
    assert seen == [1, 2]
    assert out["data"]["invoice_view"]["base"]["invoice_id"] == "inv-09"


@pytest.mark.asyncio
async def test_invoices_beyond_page_cap_give_a_note_not_a_silent_null():
    from zilliz_mcp_server.tools.zilliz import billing_compare as bc
    base = _usage(_item("in01-a", "compute", 1, 1))
    full = {"code": 0, "data": {"count": 999, "invoices": [
        _inv(n, "2027-01-01", "2027-01-31") for n in range(bc.INVOICE_PAGE_SIZE)]}}
    with patch(f"{MOD}.openapi_client.control_plane_api_request",
               side_effect=_client(base, base, invoices=full)) as m:
        out = await _run()
    inv_calls = [c for c in m.call_args_list if c.args[0] == "/v2/invoices"]
    assert len(inv_calls) == bc.MAX_INVOICE_PAGES
    assert out["data"]["invoice_view"]["base"] is None
    assert any("invoice_view.base is null" in n and "current_page" in n for n in out["notes"])


@pytest.mark.asyncio
async def test_cross_month_period_counts_only_invoices_starting_in_it():
    base = _usage(_item("in01-a", "compute", 1, 1))
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, base)):
        out = await _run(base_start="2026-09-15", base_end="2026-10-14",
                         target_start="2026-10-15", target_end="2026-11-13")
    v = out["data"]["invoice_view"]
    assert v["base"]["invoice_id"] == "inv-10"  # inv-09 started before 09-15: not counted
    assert v["target"] is None
    notes = " ".join(out["notes"])
    assert "invoice_view.base counts only invoices whose billing period STARTS" in notes
    assert "2026-09-01" in notes and "invoice_view.target counts only" in notes


@pytest.mark.asyncio
async def test_calendar_months_with_exclusive_period_end_have_no_straddle_note():
    # Real invoices end at the next period's first day 00:00 (exclusive).
    inv = {"code": 0, "data": {"count": 2, "invoices": [
        {"id": "inv-10", "periodStart": "2026-10-01T00:00:00Z", "periodEnd": "2026-11-01T00:00:00Z"},
        {"id": "inv-09", "periodStart": "2026-09-01T00:00:00Z", "periodEnd": "2026-10-01T00:00:00Z"}]}}
    base = _usage(_item("in01-a", "compute", 1, 1))
    with patch(f"{MOD}.openapi_client.control_plane_api_request",
               side_effect=_client(base, base, invoices=inv)):
        out = await _run()
    assert out["data"]["invoice_view"]["base"]["invoice_id"] == "inv-09"
    assert not any("invoice_view" in n for n in out.get("notes", []))


@pytest.mark.asyncio
async def test_null_invoice_view_is_explained():
    base = _usage(_item("in01-a", "compute", 1, 1))
    with patch(f"{MOD}.openapi_client.control_plane_api_request", side_effect=_client(base, base)):
        out = await _run(base_start="2026-07-01", base_end="2026-07-31",
                         target_start="2026-08-01", target_end="2026-08-31")
    assert out["data"]["invoice_view"] == {"base": None, "target": None}
    assert any("invoice_view.base is null: no invoice" in n for n in out["notes"])
