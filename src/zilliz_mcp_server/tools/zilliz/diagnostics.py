"""Cluster health overview: one call for status plus recent key metrics."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from zilliz_mcp_server.app import read_tool
from zilliz_mcp_server.common import hints, openapi_client
from zilliz_mcp_server.common.hints import step

logger = logging.getLogger(__name__)

# window -> (timedelta, granularity). Fine granularity on purpose: with coarse buckets
# (PT1H and above) the metrics API can return null for buckets that do contain sparse data.
WINDOWS: Dict[str, Any] = {
    "PT1H": (timedelta(hours=1), "PT30S"),
    "PT6H": (timedelta(hours=6), "PT30S"),
    "P1D": (timedelta(days=1), "PT5M"),
    "P7D": (timedelta(days=7), "PT5M"),
}

# (metric, kind, unit). Names are the ones accepted by POST /v2/clusters/{id}/metrics/query.
HEALTH_METRICS = [
    ("CU_COMPUTATION", "resource", "percent"),
    ("CU_CAPACITY", "resource", "percent"),
    ("STORAGE_USE", "resource", "GB"),
    ("REQ_SEARCH_COUNT", "count", "qps"),
    ("REQ_QUERY_COUNT", "count", "qps"),
    ("REQ_INSERT_COUNT", "count", "qps"),
    ("REQ_SEARCH_LATENCY_P99", "latency", "ms"),
    ("REQ_QUERY_LATENCY_P99", "latency", "ms"),
    ("REQ_FAIL_RATE_SEARCH", "fail_rate", "percent"),
    ("REQ_FAIL_RATE_QUERY", "fail_rate", "percent"),
    ("REQ_FAIL_RATE_INSERT", "fail_rate", "percent"),
    # Not in the published metric list, but accepted and observed to return values. A change
    # marks a scaling step, a common trigger for sudden failures or latency changes.
    ("CU_SIZE", "resource", "CUs"),
]

_PAIRED_COUNT = {
    "REQ_SEARCH_LATENCY_P99": "REQ_SEARCH_COUNT",
    "REQ_QUERY_LATENCY_P99": "REQ_QUERY_COUNT",
    "REQ_FAIL_RATE_SEARCH": "REQ_SEARCH_COUNT",
    "REQ_FAIL_RATE_QUERY": "REQ_QUERY_COUNT",
    "REQ_FAIL_RATE_INSERT": "REQ_INSERT_COUNT",
}

NOT_JUDGED_BASIS = "No published threshold; compare 'change_percent' with the previous window."
MIN_COVERAGE = 0.5  # share of buckets with data needed before two windows are compared


def _ts(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _stats(points: List[Dict[str, Any]]) -> Dict[str, Any]:
    vals = [(p["timestamp"], _num(p.get("value"))) for p in points]
    present = [(t, v) for t, v in vals if v is not None]
    if not present:
        return {"points_with_data": 0, "points_total": len(vals)}
    nums = [v for _, v in present]
    return {
        "points_with_data": len(nums),
        "points_total": len(vals),
        "latest": round(present[-1][1], 4),
        "latest_at": present[-1][0],
        "avg": round(sum(nums) / len(nums), 4),
        "max": round(max(nums), 4),
        "min": round(min(nums), 4),
    }


def split_windows(values: List[Dict[str, Any]], now: datetime, span: timedelta):
    """Split a series into (current, previous) windows by timestamp."""
    cur, prev = [], []
    start_cur = now - span
    for p in values:
        t = _ts(p.get("timestamp"))
        if t is None:
            continue
        (cur if t > start_cur else prev).append(p)
    return cur, prev


def assess(name: str, kind: str, cur: Dict[str, Any], counts: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Return {'status', 'basis'}. Only judges what has an objective basis."""
    if kind == "count":
        if cur["points_with_data"] == 0:
            return {"status": "no_data", "basis": "No data points reported in this window (null is not 0)."}
        if cur["max"] == 0:
            return {"status": "no_traffic", "basis": "Request rate was 0 for the whole window."}
        return {"status": "not_judged", "basis": NOT_JUDGED_BASIS}
    if cur["points_with_data"] == 0:
        paired = counts.get(_PAIRED_COUNT.get(name, ""), {})
        if paired and (paired.get("points_with_data", 0) == 0 or paired.get("max") == 0):
            return {"status": "no_traffic",
                    "basis": f"No data because {_PAIRED_COUNT[name]} shows no requests in this window."}
        if kind == "fail_rate" and paired.get("max"):
            return {"status": "unknown_or_no_failures",
                    "basis": f"Fail rate reported no value while {_PAIRED_COUNT[name]} shows requests were "
                             "served. This usually means no request failed, but the metric cannot confirm it; "
                             "say so rather than stating 0%."}
        return {"status": "no_data", "basis": "No data points reported in this window (null is not 0)."}
    if kind == "fail_rate":
        if cur["max"] > 0:
            return {"status": "failures_seen",
                    "basis": f"Failed requests reported (max {cur['max']}% of requests in a bucket)."}
        return {"status": "no_failures",
                "basis": "Fail rate was 0 in every bucket that reported a value. Requests rejected by rate "
                         "limiting or write quotas may not be counted as failures, so this does not rule "
                         "out throttling; check client-side errors."}
    return {"status": "not_judged", "basis": NOT_JUDGED_BASIS}


def _coverage(s: Dict[str, Any]) -> float:
    return (s.get("points_with_data", 0) / s["points_total"]) if s.get("points_total") else 0.0


def _change(cur: Dict[str, Any], prev: Dict[str, Any]) -> Optional[float]:
    a, b = cur.get("avg"), prev.get("avg")
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / b * 100, 1)


def build_report(cluster: Dict[str, Any], results: List[Dict[str, Any]], window: str, now: datetime,
                 compare_previous: bool) -> Dict[str, Any]:
    span, granularity = WINDOWS[window]
    by_name = {r.get("name"): r.get("values") or [] for r in results}
    summaries: Dict[str, Dict[str, Any]] = {}
    for name, kind, unit in HEALTH_METRICS:
        cur_pts, prev_pts = split_windows(by_name.get(name, []), now, span)
        summaries[name] = {"kind": kind, "unit": unit, "current": _stats(cur_pts),
                           "previous": _stats(prev_pts) if compare_previous else None}
    counts = {n: s["current"] for n, s in summaries.items() if s["kind"] == "count"}
    metrics_out = {}
    for name, s in summaries.items():
        entry: Dict[str, Any] = {"unit": s["unit"], **assess(name, s["kind"], s["current"], counts),
                                 "current": s["current"]}
        if compare_previous:
            entry["previous"] = s["previous"]
            cov_c, cov_p = _coverage(s["current"]), _coverage(s["previous"])
            if min(cov_c, cov_p) < MIN_COVERAGE and max(cov_c, cov_p) > 0:
                # Averages over a few reported buckets are not comparable with a fully covered window.
                entry["change_note"] = (
                    f"Not compared: data in {s['current'].get('points_with_data', 0)}/"
                    f"{s['current'].get('points_total', 0)} buckets now vs "
                    f"{s['previous'].get('points_with_data', 0)}/{s['previous'].get('points_total', 0)} before.")
            else:
                ch = _change(s["current"], s["previous"])
                if ch is not None:
                    entry["change_percent"] = ch
        metrics_out[name] = entry
    return {
        "cluster": {k: cluster.get(k) for k in ("cluster_id", "cluster_name", "status", "plan", "cu_type",
                                                 "cu_size", "region_id")},
        "window": window,
        "granularity": granularity,
        "compared_with": "previous window of the same length" if compare_previous else None,
        "metrics": metrics_out,
    }


def health_hints(report: Dict[str, Any], window: str) -> Any:
    cid = report["cluster"]["cluster_id"]
    status = report["cluster"]["status"]
    steps, notes = [], []
    if status == "SUSPENDED":
        steps.append(step("resume_cluster", "Cluster is SUSPENDED: no traffic is served until resumed.", cluster_id=cid))
    elif status and status != "RUNNING":
        steps.append(step("describe_cluster", f"Cluster is {status}; check again until RUNNING.", cluster_id=cid))
    m = report["metrics"]
    failing = [n for n, e in m.items() if e["status"] == "failures_seen"]
    moved = sorted(((n, e["change_percent"]) for n, e in m.items()
                    if abs(e.get("change_percent") or 0) >= 50 and e["status"] not in ("no_data", "no_traffic")),
                   key=lambda x: -abs(x[1]))
    granularity = WINDOWS[window][1]
    if failing:
        steps.append(step("query_cluster_metrics", "Look at when the failures happened.", cluster_id=cid,
                          period=window, granularity=granularity,
                          metric_queries=[{"metricName": n, "stat": "AVG"} for n in failing]
                          + [{"metricName": _PAIRED_COUNT[n], "stat": "AVG"} for n in failing if n in _PAIRED_COUNT]))
    if moved:
        notes.append("Largest changes vs previous window: "
                     + ", ".join(f"{n} {c:+.1f}%" for n, c in moved[:4]))
        steps.append(step("query_cluster_metrics", "Inspect the time series of the metrics that changed most.",
                          cluster_id=cid, period=window, granularity=granularity,
                          metric_queries=[{"metricName": n, "stat": "AVG"} for n, _ in moved[:3]]))
    if all(e["current"].get("points_with_data", 0) == 0 for e in m.values()):
        notes.append("No metric reported data in this window; the cluster may have been idle or not running.")
    cu = m.get("CU_SIZE", {})
    cu_cur, cu_prev = cu.get("current", {}), cu.get("previous") or {}
    sizes = [v for v in (cu_prev.get("min"), cu_prev.get("max"), cu_cur.get("min"), cu_cur.get("max")) if v is not None]
    if len(set(sizes)) > 1:
        notes.insert(0, f"CU_SIZE changed in this period (between {min(sizes):g} and {max(sizes):g} CUs, latest "
                        f"{cu_cur.get('latest', 'n/a')}): a scaling step. Compare its time with when failures or "
                        "latency changed.")
        steps.append(step("query_cluster_metrics", "See when the cluster size changed, next to failures.",
                          cluster_id=cid, period=window, granularity=granularity,
                          metric_queries=[{"metricName": "CU_SIZE", "stat": "AVG"}]
                          + [{"metricName": n, "stat": "AVG"} for n in failing]))
    sparse = [n for n, e in m.items() if 0 < _coverage(e["current"]) < MIN_COVERAGE]
    if sparse and window in ("P1D", "P7D"):
        notes.append(f"{len(sparse)} metrics have data in few {granularity} buckets; at coarser granularity the "
                     f"API can leave buckets empty. For recent detail use window 'PT1H' (PT30S buckets).")
        steps.append(step("get_cluster_health", "Finer-grained view of the last hour.", cluster_id=cid, window="PT1H"))
    notes.append("'not_judged' means no published threshold exists; values and change_percent are facts, "
                 "not a verdict.")
    return steps, notes


@read_tool()
async def get_cluster_health(cluster_id: str, window: str = "P1D", compare_previous: bool = True) -> str:
    """
    One-call health overview of a cluster: status plus recent CU usage, storage, search/query/insert
    request rate, P99 latency and failure rates, each with an assessment and its basis, compared
    with the previous window of the same length. Use this first for questions like "is my cluster
    healthy", "why is it slow lately", "how is usage trending"; then drill down with
    query_cluster_metrics.

    Args:
        cluster_id: ID of the cluster (like 'in01-xxxxxxxxxxxxxxx'), from list_clusters
        window: Time window ending now: "PT1H", "PT6H", "P1D" (default) or "P7D"
        compare_previous: Also summarize the previous window of the same length (default: True)
    Returns:
        JSON {"notes": [...], "next_steps": [...], "data": <report>}; on failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <report>.metrics.<METRIC> = {"unit", "status", "basis", "current": {avg, max, latest, latest_at,
        points_with_data, points_total}, "previous": {...}, "change_percent"}.
        status is one of: no_data (nothing reported; null is not 0), no_traffic (no requests of that
        type), no_failures (fail rate reported as 0), unknown_or_no_failures (fail rate null while
        requests were served: probably no failures, but unconfirmed; do not report 0%), failures_seen,
        not_judged (no published threshold: read the numbers and
        change_percent instead of calling them good or bad).
        Example:
        {
            "data": {
                "cluster": {"cluster_id": "inxx-xxxxxxxxxxxxxxx", "status": "RUNNING", "cu_size": 1},
                "window": "P1D", "granularity": "PT5M",
                "metrics": {
                    "REQ_SEARCH_LATENCY_P99": {"unit": "ms", "status": "not_judged",
                        "current": {"avg": 42.1, "max": 95.0}, "previous": {"avg": 30.2}, "change_percent": 39.4},
                    "REQ_FAIL_RATE_SEARCH": {"unit": "percent", "status": "no_failures"}
                }
            },
            "notes": ["'not_judged' means no published threshold exists; ..."]
        }
    """
    try:
        if window not in WINDOWS:
            raise ValueError(f"window '{window}' is not supported. Valid values: {', '.join(WINDOWS)}")
        logger.info(f"GET_CLUSTER_HEALTH: cluster_id={cluster_id}, window={window}")
        cluster_raw = openapi_client.control_plane_api_request(f"/v2/clusters/{cluster_id}").get("data") or {}
        cluster = {
            "cluster_id": cluster_raw.get("clusterId", cluster_id),
            "cluster_name": cluster_raw.get("clusterName"),
            "status": cluster_raw.get("status"),
            "plan": cluster_raw.get("plan"),
            "cu_type": cluster_raw.get("cuType"),
            "cu_size": cluster_raw.get("cuSize"),
            "region_id": cluster_raw.get("regionId"),
        }
        span, granularity = WINDOWS[window]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        start = now - (span * 2 if compare_previous else span)
        body = {
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "granularity": granularity,
            "metricQueries": [{"name": n, "stat": "AVG"} for n, _, _ in HEALTH_METRICS],
        }
        resp = openapi_client.control_plane_api_request(
            f"/v2/clusters/{cluster_id}/metrics/query", body_map=body, method="POST")
        results = (resp.get("data") or {}).get("results") or []
        report = build_report(cluster, results, window, now, compare_previous)
        return hints.ok(report, *health_hints(report, window))
    except Exception as e:
        logger.error(f"GET_CLUSTER_HEALTH ERROR: {str(e)}")
        raise hints.tool_error("get_cluster_health", e, {"cluster_id": cluster_id, "window": window}) from e
