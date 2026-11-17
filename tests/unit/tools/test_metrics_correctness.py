"""Tests for query_cluster_metrics validation and null interpretation."""

import json
from unittest.mock import patch

import pytest

from zilliz_mcp_server.common.hints import StructuredToolError
from zilliz_mcp_server.tools.zilliz import metrics as m


def _resp(*results):
    return {"code": 0, "data": {"results": list(results)}}


def _series(name, values, unit="percent"):
    ts = ["2024-06-30T16:00:00Z", "2024-06-30T16:05:00Z", "2024-06-30T16:10:00Z"]
    return {"name": name, "stat": "AVG", "unit": unit,
            "values": [{"timestamp": t, "value": v} for t, v in zip(ts, values)]}


class TestValidation:
    @pytest.mark.parametrize("bad", ["REQ_SUCCESS_RATE", "REQ_FAIL_RATE", "ENTITIES_INSERT_RATE",
                                     "REQ_BULK_INSERT_LATENCY_P99", "NOT_A_METRIC"])
    def test_rejected_names_fail_locally_with_valid_list(self, bad):
        with pytest.raises(StructuredToolError) as e:
            m.validate_metric_queries([{"metricName": bad, "stat": "AVG"}])
        p = e.value.payload
        assert p["error"] == "INVALID_ARGUMENT" and p["field"] == "metric_queries"
        assert p["expected"].startswith("Valid metric names:")
        assert "FLUSH_COUNT" in p["expected"]  # full list, not truncated
        assert p["got"] == bad
        assert bad not in m.METRICS

    def test_success_rate_points_to_per_operation_fail_rate(self):
        with pytest.raises(StructuredToolError, match="100 - fail rate"):
            m.validate_metric_queries([{"metricName": "REQ_SUCCESS_RATE"}])

    def test_stat_defaults_to_avg_and_name_is_normalized(self):
        assert m.validate_metric_queries([{"metricName": "req_search_count"}]) == [
            {"name": "REQ_SEARCH_COUNT", "stat": "AVG"}]

    def test_p99_allowed_only_for_p99_latency(self):
        assert m.validate_metric_queries([{"metricName": "REQ_SEARCH_LATENCY_P99", "stat": "P99"}])[0]["stat"] == "P99"
        with pytest.raises(StructuredToolError, match="Valid stat values for REQ_SEARCH_COUNT: AVG"):
            m.validate_metric_queries([{"metricName": "REQ_SEARCH_COUNT", "stat": "P99"}])
        with pytest.raises(StructuredToolError, match="REQ_SEARCH_LATENCY_P99"):
            m.validate_metric_queries([{"metricName": "REQ_SEARCH_LATENCY_AVG", "stat": "P99"}])

    def test_unknown_stat_rejected(self):
        with pytest.raises(StructuredToolError, match="Valid stat values"):
            m.validate_metric_queries([{"metricName": "CU_COMPUTATION", "stat": "MEDIAN"}])

    def test_empty_queries_rejected(self):
        with pytest.raises(StructuredToolError, match="metric_queries is empty"):
            m.validate_metric_queries([])

    def test_paired_count(self):
        assert m.paired_count_metric("REQ_FAIL_RATE_SEARCH") == "REQ_SEARCH_COUNT"
        assert m.paired_count_metric("REQ_QUERY_LATENCY_P99") == "REQ_QUERY_COUNT"
        assert m.paired_count_metric("REQ_FAIL_RATE_BULK_INSERT") == "REQ_BULK_INSERT_COUNT"
        assert m.paired_count_metric("CU_COMPUTATION") is None


class TestNullInterpretation:
    def test_fail_rate_null_with_traffic_is_unknown_or_no_failures(self):
        fail = _series("REQ_FAIL_RATE_SEARCH", [None, None, "2.5"])
        counts = m.series_by_timestamp([_series("REQ_SEARCH_COUNT", ["0", "7.4", "6.8"], "qps")])
        m.annotate([fail], counts)
        assert [p["value_status"] for p in fail["values"]] == ["no_requests", "unknown_or_no_failures", "reported"]
        assert fail["null_points"] == 2
        assert "REQ_SEARCH_COUNT" in fail["null_note"]
        assert "treat as 0" not in fail["null_note"]

    def test_latency_null_statuses(self):
        lat = _series("REQ_SEARCH_LATENCY_P99", [None, "5.4", None], "millisecond")
        counts = m.series_by_timestamp([_series("REQ_SEARCH_COUNT", [None, "7.4", "0"], "qps")])
        m.annotate([lat], counts)
        # paired count null (series not reported) -> no_data; paired count 0 -> no_requests
        assert [p["value_status"] for p in lat["values"]] == ["no_data", "reported", "no_requests"]

    def test_zero_is_reported_not_null(self):
        cnt = _series("REQ_SEARCH_COUNT", ["0", "0", "0"], "qps")
        m.annotate([cnt], {})
        assert all(p["value_status"] == "reported" for p in cnt["values"])
        assert "null_note" not in cnt

    def test_unexplained_null_gets_verification_note(self):
        cu = _series("CU_COMPUTATION", [None, "1.3", "1.4"])
        m.annotate([cu], {})
        assert cu["values"][0]["value_status"] == "no_data"
        assert "NOT" in cu["null_note"] or "not 0" in cu["null_note"]
        assert "CU_COMPUTATION" in cu["null_note"]


@pytest.mark.asyncio
class TestToolIntegration:
    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_invalid_metric_never_calls_api(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        with pytest.raises(Exception, match="Valid metric names"):
            await query_cluster_metrics(cluster_id="in01-x", period="PT1H",
                                        metric_queries=[{"metricName": "REQ_SUCCESS_RATE", "stat": "AVG"}])
        mock_client.control_plane_api_request.assert_not_called()

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_fail_rate_nulls_trigger_paired_count_lookup(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        mock_client.control_plane_api_request.side_effect = [
            _resp(_series("REQ_FAIL_RATE_SEARCH", [None, None, None])),
            _resp(_series("REQ_SEARCH_COUNT", ["0", "7.4", None], "qps")),
        ]
        out = json.loads(await query_cluster_metrics(
            cluster_id="in01-x", period="PT15M", granularity="PT5M",
            metric_queries=[{"metricName": "REQ_FAIL_RATE_SEARCH"}]))
        res = out["data"]["results"]
        assert len(res) == 1  # the helper series is not added to the output
        assert [r["status"] for r in res[0]["null_runs"]] == ["no_requests", "unknown_or_no_failures", "no_data"]
        assert res[0]["values"] == [] and res[0]["buckets"] == 3 and res[0]["null_points"] == 3
        second = mock_client.control_plane_api_request.call_args_list[1]
        assert second.kwargs["body_map"] == {"granularity": "PT5M", "period": "PT15M",
                                             "metricQueries": [{"name": "REQ_SEARCH_COUNT", "stat": "AVG"}]}

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_paired_count_already_requested_is_reused(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        mock_client.control_plane_api_request.return_value = _resp(
            _series("REQ_FAIL_RATE_SEARCH", [None, "1", None]),
            _series("REQ_SEARCH_COUNT", ["3", "3", "0"], "qps"))
        out = json.loads(await query_cluster_metrics(
            cluster_id="in01-x", period="PT15M",
            metric_queries=[{"metricName": "REQ_FAIL_RATE_SEARCH"}, {"metricName": "REQ_SEARCH_COUNT"}]))
        assert mock_client.control_plane_api_request.call_count == 1
        r0 = out["data"]["results"][0]
        assert [r["status"] for r in r0["null_runs"]] == ["unknown_or_no_failures", "no_requests"]
        assert [p["value"] for p in r0["values"]] == ["1"]
        assert "value_status" not in r0["values"][0]

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_paired_lookup_failure_falls_back_to_note(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        mock_client.control_plane_api_request.side_effect = [
            _resp(_series("REQ_FAIL_RATE_QUERY", [None, None, None])), Exception("boom")]
        out = json.loads(await query_cluster_metrics(
            cluster_id="in01-x", period="PT15M", metric_queries=[{"metricName": "REQ_FAIL_RATE_QUERY"}]))
        r = out["data"]["results"][0]
        assert r["null_runs"] == [{"status": "no_data", "from": r["null_runs"][0]["from"],
                                   "to": r["null_runs"][0]["to"], "points": 3}]
        assert "not 0" in r["null_note"]

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_vcu_error_is_explained(self, mock_client):
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        from zilliz_mcp_server.common.hints import ZillizAPIError
        mock_client.control_plane_api_request.side_effect = ZillizAPIError("Bad request.", code=100)
        with pytest.raises(StructuredToolError, match="Serverless clusters") as e:
            await query_cluster_metrics(cluster_id="in01-x", period="PT1H",
                                        metric_queries=[{"metricName": "READ_VCU"}])
        assert e.value.payload["field"] == "metric_queries"

    @patch('zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client')
    async def test_vcu_note_does_not_hide_auth_or_permission_advice(self, mock_client):
        from zilliz_mcp_server.common.hints import ZillizAPIError
        from zilliz_mcp_server.tools.zilliz.zilliz_tools import query_cluster_metrics
        for err, kind in ((ZillizAPIError("The apikey is illegal", code=21119, http_status=401), "AUTH_FAILED"),
                          (ZillizAPIError("Missing ACL permission: resource=cluster, action=view",
                                          code=96041), "PERMISSION_DENIED")):
            mock_client.control_plane_api_request.side_effect = err
            with pytest.raises(StructuredToolError) as e:
                await query_cluster_metrics(cluster_id="in01-x", period="PT1H",
                                            metric_queries=[{"metricName": "READ_VCU"}])
            assert e.value.payload["error"] == kind
            assert "Serverless" not in e.value.payload.get("fix", "")
