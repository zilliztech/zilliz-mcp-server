"""query_cluster_metrics output size: compact null runs and the response budget."""

import json

from zilliz_mcp_server.tools.zilliz import metrics as m


def pts(values, prefix="2026-11-16T"):
    return [{"timestamp": f"{prefix}{i // 60:02d}:{i % 60:02d}:00Z", "value": v} for i, v in enumerate(values)]


def annotated(name, values, statuses=None):
    ps = pts(values)
    for i, p in enumerate(ps):
        p["value_status"] = "reported" if p["value"] is not None else (statuses or {}).get(i, "no_data")
    return {"name": name, "stat": "AVG", "unit": "percent", "values": ps}


class TestCompact:
    def test_runs_replace_per_point_status(self):
        r = m.compact([annotated("REQ_FAIL_RATE_SEARCH", [None, None, "1", None, None],
                                 {0: "no_requests", 1: "unknown_or_no_failures"})])[0]
        assert r["buckets"] == 5
        assert r["values"] == [{"timestamp": "2026-11-16T00:02:00Z", "value": "1"}]
        assert [(x["status"], x["points"]) for x in r["null_runs"]] == [
            ("no_requests", 1), ("unknown_or_no_failures", 1), ("no_data", 2)]
        assert r["null_runs"][2] == {"status": "no_data", "from": "2026-11-16T00:03:00Z",
                                     "to": "2026-11-16T00:04:00Z", "points": 2}
        assert r["null_points"] == 4

    def test_zero_stays_a_value(self):
        r = m.compact([annotated("CU_CAPACITY", ["0", "0"])])[0]
        assert [p["value"] for p in r["values"]] == ["0", "0"]
        assert "null_runs" not in r

    def test_sparse_series_is_small(self):
        res = [annotated(f"S{i}", [None] * 167 + ["1"]) for i in range(5)]
        assert len(json.dumps({"results": m.compact(res)})) < 2_000


class TestFitResults:
    def test_fits_untouched(self):
        out, info = m.fit_results([annotated("A", ["1"] * 10)])
        assert info is None and len(out[0]["values"]) == 10

    def test_dense_over_budget_keeps_recent_tail(self):
        res = [annotated(f"S{i}", [str(1000 + j) for j in range(168)]) for i in range(5)]
        out, info = m.fit_results(res, budget=20_000)
        assert len(json.dumps({"results": out})) <= 20_000
        assert info["total"] == 168 and 0 < info["kept"] < 168
        for r in out:
            assert r["buckets"] == info["kept"]
            assert r["values"][-1]["timestamp"] == res[0]["values"][-1]["timestamp"]
        assert info["kept_from"] == res[0]["values"][-info["kept"]]["timestamp"]
        assert info["window_start"] == res[0]["values"][0]["timestamp"]

    def test_trim_hints(self):
        info = {"kept": 50, "total": 168, "bytes_total": 70000,
                "window_start": "2026-11-09T00:00:00Z", "kept_from": "2026-11-14T22:00:00Z"}
        st, note = m.trim_hints(info, "in01-x", [{"metricName": "A", "stat": "AVG"}], "PT1H")
        assert "most recent 50 of 168 buckets" in note
        assert st["args"]["start"] == "2026-11-09T00:00:00Z" and st["args"]["end"] == "2026-11-14T22:00:00Z"
        assert st["args"]["granularity"] == "PT1H"

    def test_requery_end_is_first_kept_bucket(self):
        # The API's end is exclusive (observed), so end = first kept bucket neither overlaps nor gaps.
        info = {"kept": 132, "total": 360, "bytes_total": 90000,
                "window_start": "2026-11-16T10:00:00Z", "kept_from": "2026-11-16T13:48:00Z"}
        st, _ = m.trim_hints(info, "c", [{"metricName": "A", "stat": "AVG"}], "PT1M")
        assert st["args"]["end"] == "2026-11-16T13:48:00Z"


class TestWholeOutputBudget:
    def test_notes_and_steps_count_toward_budget(self, monkeypatch):
        import asyncio
        from unittest.mock import patch
        from zilliz_mcp_server.common.budget import RESULT_BUDGET
        from zilliz_mcp_server.tools.zilliz import zilliz_tools as zt
        names = ["CU_CAPACITY", "CU_COMPUTATION", "STORAGE_USE", "CU_SIZE", "REPLICA_COUNT"]
        names = [n for n in names if n in m.METRICS][:5]
        series = [{"name": n, "stat": "AVG", "unit": "x",
                   "values": pts([str(123456 + j) for j in range(360)])} for n in names]
        # A long note pushes notes + next_steps over the margin left by a data-only budget.
        monkeypatch.setattr(zt.ns, "query_cluster_metrics", lambda data, cid: ([], ["n" * 2500]))
        with patch.object(zt.openapi_client, "control_plane_api_request",
                          return_value={"code": 0, "data": {"results": series}}):
            out = asyncio.run(zt.query_cluster_metrics(
                cluster_id="in01-x", period="PT6H", granularity="PT1M",
                metric_queries=[{"metricName": n, "stat": "AVG"} for n in names]))
        assert len(out.encode()) <= RESULT_BUDGET
        j = json.loads(out)
        assert any("trimmed" in n for n in j["notes"])
