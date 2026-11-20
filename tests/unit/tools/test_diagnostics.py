"""Unit tests for get_cluster_health (tools/zilliz/diagnostics.py)."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from zilliz_mcp_server.tools.zilliz import diagnostics as d

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
CLUSTER = {"cluster_id": "in01-abc", "status": "RUNNING", "cluster_name": "c"}


def series(values, span=timedelta(hours=1), step=timedelta(minutes=30)):
    """Points oldest -> newest ending at NOW, covering previous+current windows."""
    pts, t = [], NOW - span * 2 + step
    for v in values:
        pts.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": None if v is None else str(v)})
        t += step
    return pts


def results(**by_name):
    return [{"name": n, "values": by_name.get(n, series([None] * 4))} for n, _, _ in d.HEALTH_METRICS]


def report(**by_name):
    return d.build_report(CLUSTER, results(**by_name), "PT1H", NOW, True)


class TestAssess:
    def test_null_is_no_data_not_zero(self):
        r = report()
        assert r["metrics"]["CU_COMPUTATION"]["status"] == "no_data"

    def test_latency_null_with_zero_traffic_is_no_traffic(self):
        r = report(REQ_SEARCH_COUNT=series([0, 0, 0, 0]))
        assert r["metrics"]["REQ_SEARCH_COUNT"]["status"] == "no_traffic"
        assert r["metrics"]["REQ_SEARCH_LATENCY_P99"]["status"] == "no_traffic"
        assert r["metrics"]["REQ_FAIL_RATE_SEARCH"]["status"] == "no_traffic"

    def test_fail_rate(self):
        r = report(REQ_SEARCH_COUNT=series([5, 5, 5, 5]), REQ_FAIL_RATE_SEARCH=series([0, 0, 0, 2.5]),
                   REQ_FAIL_RATE_QUERY=series([0, 0, 0, 0]), REQ_QUERY_COUNT=series([1, 1, 1, 1]))
        assert r["metrics"]["REQ_FAIL_RATE_SEARCH"]["status"] == "failures_seen"
        assert r["metrics"]["REQ_FAIL_RATE_QUERY"]["status"] == "no_failures"

    def test_no_threshold_means_not_judged_with_change(self):
        r = report(REQ_SEARCH_LATENCY_P99=series([10, 10, 20, 20]), REQ_SEARCH_COUNT=series([1, 1, 1, 1]))
        e = r["metrics"]["REQ_SEARCH_LATENCY_P99"]
        assert e["status"] == "not_judged" and e["change_percent"] == 100.0
        assert e["current"]["avg"] == 20.0 and e["previous"]["avg"] == 10.0

    def test_sparse_previous_window_not_compared(self):
        r = report(REQ_SEARCH_COUNT=series([None, None, None, 1, 5, 5, 5, 5], step=timedelta(minutes=15)))
        e = r["metrics"]["REQ_SEARCH_COUNT"]
        assert "change_percent" not in e
        assert "1/2 buckets before" not in e["change_note"] and "Not compared" in e["change_note"]


    def test_fail_rate_null_with_traffic_is_unknown_or_no_failures(self):
        r = report(REQ_SEARCH_COUNT=series([5, 5, 5, 5]))
        e = r["metrics"]["REQ_FAIL_RATE_SEARCH"]
        assert e["status"] == "unknown_or_no_failures" and "0%" in e["basis"]

    def test_no_failures_basis_only_claims_reported_buckets(self):
        r = report(REQ_SEARCH_COUNT=series([5, 5, 5, 5]), REQ_FAIL_RATE_SEARCH=series([0, None, 0, None]))
        e = r["metrics"]["REQ_FAIL_RATE_SEARCH"]
        assert e["status"] == "no_failures" and "reported a value" in e["basis"]


class TestHints:
    def test_suspended_points_to_resume(self):
        r = d.build_report({**CLUSTER, "status": "SUSPENDED"}, results(), "PT1H", NOW, True)
        steps, notes = d.health_hints(r, "PT1H")
        assert steps[0] == {"tool": "resume_cluster", "args": {"cluster_id": "in01-abc"}, "why": steps[0]["why"]}
        assert any("No metric reported data" in n for n in notes)

    def test_failures_point_to_query_cluster_metrics_with_paired_count(self):
        r = report(REQ_SEARCH_COUNT=series([5, 5, 5, 5]), REQ_FAIL_RATE_SEARCH=series([0, 0, 0, 2.5]))
        steps, _ = d.health_hints(r, "PT1H")
        q = steps[0]
        assert q["tool"] == "query_cluster_metrics" and q["args"]["period"] == "PT1H"
        names = [m["metricName"] for m in q["args"]["metric_queries"]]
        assert names == ["REQ_FAIL_RATE_SEARCH", "REQ_SEARCH_COUNT"]


class TestTool:
    pytestmark = pytest.mark.asyncio

    @patch("zilliz_mcp_server.tools.zilliz.diagnostics.openapi_client")
    async def test_calls_api_once_for_both_windows(self, client):
        client.control_plane_api_request.side_effect = [
            {"code": 0, "data": {"clusterId": "in01-abc", "status": "RUNNING"}},
            {"code": 0, "data": {"results": results()}},
        ]
        out = json.loads(await d.get_cluster_health("in01-abc", window="P1D"))
        assert out["data"]["window"] == "P1D" and out["data"]["granularity"] == "PT5M"
        body = client.control_plane_api_request.call_args_list[1].kwargs["body_map"]
        start = datetime.fromisoformat(body["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(body["end"].replace("Z", "+00:00"))
        assert end - start == timedelta(days=2)
        assert {q["name"] for q in body["metricQueries"]} == {n for n, _, _ in d.HEALTH_METRICS}

    async def test_bad_window_is_invalid_argument(self):
        with pytest.raises(Exception) as ei:
            await d.get_cluster_health("in01-abc", window="30d")
        payload = json.loads(str(ei.value))
        assert payload["error"] == "INVALID_ARGUMENT" and "P7D" in payload["message"]
