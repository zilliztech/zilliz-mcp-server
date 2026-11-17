"""Tests for get_cluster_activity_history."""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from zilliz_mcp_server.tools.zilliz import activity as a


def series(name, points):
    return {"name": name, "values": [{"timestamp": t, "value": v} for t, v in points]}


class TestHelpers:
    def test_chunks_cover_window(self):
        s = datetime(2026, 5, 20, tzinfo=timezone.utc)
        e = datetime(2026, 11, 16, tzinfo=timezone.utc)
        parts = a.chunks(s, e)
        assert parts[0][0] == s and parts[-1][1] == e and len(parts) == 26
        assert all(p[1] == q[0] for p, q in zip(parts, parts[1:]))

    def test_summarize_counts_only_positive_buckets(self):
        got = [[series("REQ_SEARCH_COUNT", [("2026-11-15T10:00:00Z", None), ("2026-11-15T10:05:00Z", "0")])],
               [series("REQ_SEARCH_COUNT", [("2026-11-16T21:05:00Z", "3.5"), ("2026-11-16T22:00:00Z", "14.2")]),
                series("REQ_QUERY_COUNT", [("2026-11-16T21:05:00Z", None)])]]
        out = a.summarize(got, ["REQ_SEARCH_COUNT", "REQ_QUERY_COUNT"])
        s = out["REQ_SEARCH_COUNT"]
        assert s["active_days"] == 1 and s["peak_by_day"] == {"2026-11-16": 14.2}
        assert s["first_active"] == "2026-11-16T21:05:00Z" and s["last_active"] == "2026-11-16T22:00:00Z"
        assert s["buckets_with_value"] == 3
        assert out["REQ_QUERY_COUNT"]["active_days"] == 0 and out["REQ_QUERY_COUNT"]["first_active"] is None

    def test_boundary_bucket_counted_once(self):
        b = series("REQ_SEARCH_COUNT", [("2026-11-16T00:00:00Z", "1")])
        out = a.summarize([[b], [b]], ["REQ_SEARCH_COUNT"])
        assert out["REQ_SEARCH_COUNT"]["buckets_with_value"] == 1

    def test_fit_collapses_to_weeks_when_large(self):
        days = {f"2026-{m:02d}-{d:02d}": 1.0 for m in range(5, 12) for d in range(1, 29)}
        report = {"metrics": {f"REQ_{i}_COUNT": {"peak_by_day": dict(days)} for i in range(5)}}
        assert a.fit(report, budget=10_000) is not None
        m = report["metrics"]["REQ_0_COUNT"]
        assert "peak_by_day" not in m and all(datetime.strptime(k, "%Y-%m-%d").weekday() == 0
                                              for k in m["peak_by_week"])


@pytest.mark.asyncio
class TestTool:
    @patch("zilliz_mcp_server.tools.zilliz.activity.openapi_client")
    async def test_reports_first_last_active(self, client):
        def req(uri, body_map=None, method="GET"):
            if method == "GET":
                return {"data": {"createTime": "2026-01-01T00:00:00Z"}}
            if body_map["start"].startswith(datetime.now(timezone.utc).strftime("%Y-%m-%d")[:7]):
                return {"data": {"results": [series("REQ_SEARCH_COUNT", [("2026-11-16T21:05:00Z", "2")])]}}
            return {"data": {"results": [series("REQ_SEARCH_COUNT", [("2026-06-01T00:00:00Z", None)])]}}
        client.control_plane_api_request.side_effect = req
        out = json.loads(await a.get_cluster_activity_history("c1", days=30, metrics=["REQ_SEARCH_COUNT"]))
        assert out["data"]["chunks"] == 5 and out["data"]["failed_chunks"] == 0
        assert "Requests seen" in out["notes"][0]
        assert out["next_steps"][0]["tool"] == "query_cluster_metrics"

    @patch("zilliz_mcp_server.tools.zilliz.activity.openapi_client")
    async def test_no_traffic_and_window_starts_at_creation(self, client):
        created = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT00:00:00Z")
        def req(uri, body_map=None, method="GET"):
            if method == "GET":
                return {"data": {"createTime": created}}
            return {"data": {"results": [series("REQ_SEARCH_COUNT", [("t", None)])]}}
        client.control_plane_api_request.side_effect = req
        out = json.loads(await a.get_cluster_activity_history("c1"))
        assert out["data"]["window_start"] == created and out["data"]["chunks"] == 1
        assert out["notes"][0].startswith("No request metric was above 0")
        assert "next_steps" not in out

    @patch("zilliz_mcp_server.tools.zilliz.activity.openapi_client")
    async def test_partial_failure_goes_to_notes(self, client):
        calls = {"n": 0}
        def req(uri, body_map=None, method="GET"):
            if method == "GET":
                return {"data": {}}
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("upstream 500")
            return {"data": {"results": []}}
        client.control_plane_api_request.side_effect = req
        out = json.loads(await a.get_cluster_activity_history("c1", days=21))
        assert out["data"]["failed_chunks"] == 1
        assert any("could not be read" in n and "upstream 500" in n for n in out["notes"])

    @patch("zilliz_mcp_server.tools.zilliz.activity.openapi_client")
    async def test_all_chunks_timeout_is_network_error(self, client, monkeypatch):
        import time
        monkeypatch.setattr(a, "TOTAL_TIMEOUT_S", 0.05)
        def req(uri, body_map=None, method="GET"):
            if method == "GET":
                return {"data": {}}
            time.sleep(0.3)
            return {"data": {"results": []}}
        client.control_plane_api_request.side_effect = req
        with pytest.raises(Exception) as ei:
            await a.get_cluster_activity_history("c1", days=7)
        payload = json.loads(str(ei.value))
        assert payload["error"] == "NETWORK_ERROR"
        assert "timed out" in payload["fix"]
        assert payload["next_steps"][0]["tool"] == "get_cluster_activity_history"

    @pytest.mark.parametrize("days", [0, 181, "7"])
    async def test_bad_days(self, days):
        with pytest.raises(Exception) as ei:
            await a.get_cluster_activity_history("c1", days=days)
        assert "INVALID_ARGUMENT" in str(ei.value)

    @pytest.mark.parametrize("metric", ["CU_CAPACITY", "ENTITIES_COUNT"])
    async def test_non_request_metric_rejected(self, metric):
        with pytest.raises(Exception) as ei:
            await a.get_cluster_activity_history("c1", metrics=[metric])
        assert "INVALID_ARGUMENT" in str(ei.value) and "REQ_" in str(ei.value)

    @patch("zilliz_mcp_server.tools.zilliz.activity.TOTAL_TIMEOUT_S", 0.05)
    @patch("zilliz_mcp_server.tools.zilliz.activity.openapi_client")
    async def test_all_chunks_timed_out_is_an_error(self, client):
        import time

        def req(uri, body_map=None, method="GET"):
            if method == "GET":
                return {"data": {}}
            time.sleep(0.3)
            return {"data": {"results": []}}
        client.control_plane_api_request.side_effect = req
        with pytest.raises(Exception) as ei:
            await a.get_cluster_activity_history("c1", days=35)
        assert "none of the 5 metric chunks finished" in str(ei.value)
