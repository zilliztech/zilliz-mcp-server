"""Tests for coarse-granularity coverage hints in query_cluster_metrics."""

import json
from unittest.mock import patch

import pytest

from zilliz_mcp_server.tools.zilliz import metrics as m
from zilliz_mcp_server.tools.zilliz import zilliz_tools

CID = "in01-abc"
MQ = [{"metricName": "REQ_SEARCH_COUNT"}]


def res(values):
    return [{"name": "REQ_SEARCH_COUNT", "values": [{"timestamp": f"t{i}", "value": v} for i, v in enumerate(values)]}]


class TestDuration:
    @pytest.mark.parametrize("iso,sec", [("PT30S", 30), ("PT5M", 300), ("PT1H", 3600), ("P1D", 86400),
                                         ("P180D", 180 * 86400), ("P1DT12H", 129600)])
    def test_parse(self, iso, sec):
        assert m.duration_seconds(iso) == sec

    @pytest.mark.parametrize("iso", ["P6M", "P2W", "", None, "P"])
    def test_unsupported(self, iso):
        assert m.duration_seconds(iso) is None

    def test_finest_granularity_respects_point_cap(self):
        assert m.finest_granularity(7 * 86400) == "PT30S"
        assert m.finest_granularity(30 * 86400) == "PT2M"
        assert m.finest_granularity(180 * 86400) == "PT15M"
        for days in (1, 7, 30, 90, 180, 366):
            g = m.finest_granularity(days * 86400)
            assert days * 86400 / m.duration_seconds(g) <= m.MAX_POINTS


class TestCoverageHints:
    def test_all_null_coarse_suggests_readable_recent_windows(self):
        steps, notes = m.coverage_hints(res([None] * 180), CID, MQ, "P1D", "P180D", None, None)
        assert "does NOT mean no traffic" in notes[0] and "0/180" in notes[0]
        assert steps[0]["args"] == {"cluster_id": CID, "period": "PT3H", "granularity": "PT30S",
                                    "metric_queries": MQ}
        assert (steps[1]["args"]["period"], steps[1]["args"]["granularity"]) == ("PT15H", "PT2M")

    @pytest.mark.parametrize("n_metrics", [1, 2, 4, 6])
    def test_suggestions_stay_readable(self, n_metrics):
        mq = [{"metricName": "REQ_SEARCH_COUNT"}] * n_metrics
        steps, _ = m.coverage_hints(res([None] * 180), CID, mq, "P1D", "P180D", None, None)
        assert steps
        for s in steps:
            pts = m.duration_seconds(s["args"]["period"]) / m.duration_seconds(s["args"]["granularity"])
            assert pts * n_metrics <= m.READABLE_POINTS

    def test_one_day_at_pt1h(self):
        steps, _ = m.coverage_hints(res([None] * 24), CID, MQ, "PT1H", "P1D", None, None)
        assert [(s["args"]["period"], s["args"]["granularity"]) for s in steps] == [("PT3H", "PT30S"),
                                                                                   ("PT15H", "PT2M")]

    def test_start_end_window_keeps_its_last_part(self):
        s, e = "2026-11-01T00:00:00Z", "2026-11-08T00:00:00Z"
        steps, _ = m.coverage_hints(res([None] * 168), CID, MQ, "PT1H", None, s, e)
        a = steps[0]["args"]
        assert a["start"] == "2026-11-07T21:00:00Z" and a["end"] == e and "period" not in a

    def test_series_summary(self):
        r = res([None, "2", None, "5.5", None])
        r[0]["values"] = [{"timestamp": f"2026-11-16T0{i}:00:00Z", "value": p["value"]}
                          for i, p in enumerate(r[0]["values"])]
        s = m.series_summary(r)
        assert "REQ_SEARCH_COUNT: 2/5 buckets with a value" in s
        assert "first 2026-11-16T01:00:00Z, last 2026-11-16T03:00:00Z, max 5.5" in s
        assert m.series_summary(res(["1", "2"])) is None
        assert "0/3 buckets" in m.series_summary(res([None] * 3))

    def test_gauge_zeros_next_to_values_are_suspect_at_coarse_granularity(self):
        cu = [{"name": "CU_CAPACITY", "values": [{"timestamp": f"t{i}", "value": "0"} for i in range(167)]
               + [{"timestamp": "t167", "value": "13.11"}]}]
        assert m.suspect_zero_buckets(cu[0], "PT1H") == 167
        assert m.suspect_zero_buckets(cu[0], "PT1M") == 0
        s = m.series_summary(cu, "PT1H")
        assert "167 of them report 0" in s and "NOT 0%" in s
        steps, notes = m.coverage_hints(cu, CID, [{"metricName": "CU_CAPACITY"}], "PT1H", "P7D", None, None)
        assert steps and "1/168" in notes[0]
        # a real all-zero gauge, or a count metric with zeros, is left alone
        flat = [{"name": "CU_CAPACITY", "values": [{"timestamp": "t", "value": "0"}] * 24}]
        assert m.suspect_zero_buckets(flat[0], "PT1H") == 0
        cnt = [{"name": "REQ_SEARCH_COUNT", "values": [{"timestamp": "t", "value": "0"}] * 20
                + [{"timestamp": "t", "value": "3"}]}]
        assert m.suspect_zero_buckets(cnt[0], "PT1H") == 0

    def test_unexplained_null_note_is_consistent(self):
        results = res([None] * 168)
        m.annotate(results, {})
        _, notes = m.coverage_hints(results, CID, MQ, "PT1H", "P7D", None, None)
        text = results[0]["null_note"] + " ".join(notes)
        assert "report 0 (not null)" not in text
        assert "never been called" not in text
        assert "coarser than PT2M" in results[0]["null_note"]

    def test_good_coverage_is_quiet(self):
        assert m.coverage_hints(res(["1"] * 24), CID, MQ, "PT1H", "P1D", None, None) == ([], [])

    def test_fine_granularity_is_quiet(self):
        assert m.coverage_hints(res([None] * 120), CID, MQ, "PT30S", "PT1H", None, None) == ([], [])
        assert m.coverage_hints(res([None] * 30), CID, MQ, "PT2M", "PT1H", None, None) == ([], [])


@pytest.mark.asyncio
@patch("zilliz_mcp_server.tools.zilliz.zilliz_tools.openapi_client")
async def test_tool_returns_coverage_hint(client):
    client.control_plane_api_request.return_value = {"code": 0, "data": {"results": res([None, None, "2.0", None])}}
    out = json.loads(await zilliz_tools.query_cluster_metrics(
        cluster_id=CID, period="P7D", granularity="P1D", metric_queries=MQ))
    assert out["next_steps"][0]["args"]["granularity"] == "PT30S"
    assert any("does NOT mean no traffic" in n for n in out["notes"])
    assert out["notes"][0].startswith("Per series: REQ_SEARCH_COUNT: 1/4 buckets with a value")
    r0 = out["data"]["results"][0]
    assert [x["status"] for x in r0["null_runs"]] == ["no_data", "no_data"]
    assert [x["points"] for x in r0["null_runs"]] == [2, 1]
    assert [p["value"] for p in r0["values"]] == ["2.0"]


def test_fail_rate_nulls_do_not_trigger_when_counts_are_covered():
    results = res(["1"] * 24) + [{"name": "REQ_FAIL_RATE_SEARCH", "values": [{"timestamp": "t", "value": None}] * 24}]
    assert m.coverage_hints(results, CID, MQ, "PT1H", "P1D", None, None) == ([], [])


@pytest.mark.asyncio
async def test_month_period_rejected_locally():
    with pytest.raises(Exception) as ei:
        await zilliz_tools.query_cluster_metrics(cluster_id=CID, period="P6M", granularity="P1D", metric_queries=MQ)
    p = json.loads(str(ei.value))
    assert p["error"] == "INVALID_ARGUMENT" and "P180D" in p["message"]
