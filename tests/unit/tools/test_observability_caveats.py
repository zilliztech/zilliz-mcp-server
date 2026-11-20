"""Observability caveats: undocumented resource metrics and fail-rate limits."""

from datetime import datetime, timedelta, timezone

from zilliz_mcp_server.tools.zilliz import diagnostics as d
from zilliz_mcp_server.tools.zilliz import metrics as m

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
CLUSTER = {"cluster_id": "in01-abc", "status": "RUNNING", "cluster_name": "c"}


def series(values, step=timedelta(minutes=30)):
    pts, t = [], NOW - timedelta(hours=2) + step
    for v in values:
        pts.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": None if v is None else str(v)})
        t += step
    return pts


def report(**by_name):
    res = [{"name": n, "values": by_name.get(n, series([None] * 4))} for n, _, _ in d.HEALTH_METRICS]
    return d.build_report(CLUSTER, res, "PT1H", NOW, True)


class TestCatalog:
    def test_cu_size_and_replica_count_accepted(self):
        out = m.validate_metric_queries([{"metricName": "CU_SIZE", "stat": "AVG"},
                                         {"metricName": "REPLICA_COUNT", "stat": "AVG"}])
        assert [q["name"] for q in out] == ["CU_SIZE", "REPLICA_COUNT"]

    def test_described_as_observed(self):
        for name in ("CU_SIZE", "REPLICA_COUNT"):
            assert "observed" in m.METRICS[name]
            assert "not in the published metric list" in m.METRICS[name]


class TestFailRateCaveat:
    def test_present_with_fail_rate_series(self):
        note = m.fail_rate_caveat([{"name": "REQ_SEARCH_COUNT"}, {"name": "REQ_FAIL_RATE_SEARCH"}])
        assert note == m.FAIL_RATE_CAVEAT
        assert "may not count requests rejected by rate limiting or write quotas" in note
        assert "0% does not prove nothing was rejected" in note
        assert "client logs" in note
        assert len(note) <= 350  # kept short: notes are capped and emitted before data

    def test_absent_without_fail_rate_series(self):
        assert m.fail_rate_caveat([{"name": "CU_COMPUTATION"}]) is None
        assert m.fail_rate_caveat([]) is None


class TestCoverageIgnoresAlwaysReported:
    def _hourly(self, present):
        return [{"timestamp": f"t{i}", "value": "1" if i in present else None} for i in range(168)]

    def test_full_cu_size_does_not_hide_sparse_series(self):
        res = [{"name": "CU_SIZE", "values": self._hourly(set(range(168)))},
               {"name": "CU_CAPACITY", "values": self._hourly({5, 100})}]
        q = [{"metricName": "CU_SIZE", "stat": "AVG"}, {"metricName": "CU_CAPACITY", "stat": "AVG"}]
        steps, notes = m.coverage_hints(res, "in01-abc", q, "PT1H", "P7D", None, None)
        assert notes and steps

    def test_cu_size_alone_is_still_judged(self):
        res = [{"name": "CU_SIZE", "values": self._hourly(set(range(168)))}]
        q = [{"metricName": "CU_SIZE", "stat": "AVG"}]
        assert m.coverage_hints(res, "in01-abc", q, "PT1H", "P7D", None, None) == ([], [])


class TestDiagnosticsCuSize:
    def test_cu_size_is_a_health_metric(self):
        assert ("CU_SIZE", "resource", "CUs") in d.HEALTH_METRICS

    def test_change_produces_note_and_step(self):
        r = report(CU_SIZE=series([4, 4, 4, 8]), REQ_FAIL_RATE_SEARCH=series([0, 0, 0, 5]),
                   REQ_SEARCH_COUNT=series([10, 10, 10, 10]))
        steps, notes = d.health_hints(r, "PT1H")
        assert notes[0].startswith("CU_SIZE changed in this period (between 4 and 8 CUs, latest 8")
        cu_steps = [s for s in steps if s["why"].startswith("See when the cluster size changed")]
        assert cu_steps
        names = [q["metricName"] for q in cu_steps[0]["args"]["metric_queries"]]
        assert names == ["CU_SIZE", "REQ_FAIL_RATE_SEARCH"]

    def test_constant_size_no_note(self):
        r = report(CU_SIZE=series([4, 4, 4, 4]))
        _, notes = d.health_hints(r, "PT1H")
        assert not any("CU_SIZE changed" in n for n in notes)

    def test_no_failures_basis_mentions_rate_limiting(self):
        r = report(REQ_FAIL_RATE_SEARCH=series([0, 0, 0, 0]), REQ_SEARCH_COUNT=series([1, 1, 1, 1]))
        e = r["metrics"]["REQ_FAIL_RATE_SEARCH"]
        assert e["status"] == "no_failures"
        assert "rate limiting" in e["basis"]
