"""Metric catalog, local validation and null interpretation for query_cluster_metrics.

The catalog only lists metric names that the Query Cluster Metrics API
(POST /v2/clusters/{CLUSTER_ID}/metrics/query) actually accepts.
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from zilliz_mcp_server.common.budget import RESULT_BUDGET
from zilliz_mcp_server.common.hints import StructuredToolError, step

# Request operations that have count / latency / failure-rate series.
_OPS = ["INSERT", "BULK_INSERT", "UPSERT", "DELETE", "SEARCH", "QUERY"]

# name -> short description. Order is the order shown to the model.
METRICS: Dict[str, str] = {
    # Resource
    "CU_COMPUTATION": "Compute unit computation usage (percent)",
    "CU_CAPACITY": "Compute unit capacity usage (percent)",
    "STORAGE_USE": "Storage used (GB)",
    "CLUSTER_WRITE_CAPACITY": "Write capacity usage (percent)",
    "READ_VCU": "Read vCU consumption (Serverless clusters only)",
    "WRITE_VCU": "Write vCU consumption (Serverless clusters only)",
    # Accepted by the metrics endpoint and observed to return values, but not in the published
    # metric list. A change in CU_SIZE marks a scaling step (manual or autoscaling).
    "CU_SIZE": "Cluster size in CUs (observed; not in the published metric list)",
    "REPLICA_COUNT": "Number of replicas (observed; not in the published metric list)",
    # Request throughput
    "REQ_INSERT_COUNT": "Insert requests per second (qps)",
    "REQ_BULK_INSERT_COUNT": "Bulk insert requests per second (qps)",
    "REQ_UPSERT_COUNT": "Upsert requests per second (qps)",
    "REQ_DELETE_COUNT": "Delete requests per second (qps)",
    "REQ_SEARCH_COUNT": "Search requests per second (qps)",
    "REQ_QUERY_COUNT": "Query requests per second (qps)",
    "VECTOR_REQ_INSERT_COUNT": "Vectors inserted per second (vps)",
    "VECTOR_REQ_BULK_INSERT_COUNT": "Vectors bulk-inserted per second (vps)",
    "VECTOR_REQ_UPSERT_COUNT": "Vectors upserted per second (vps)",
    "VECTOR_REQ_DELETE_COUNT": "Vectors deleted per second (vps)",
    "VECTOR_REQ_SEARCH_COUNT": "Query vectors searched per second (vps)",
    "SLOW_QUERY_COUNT": "Slow queries per minute (count/m)",
    # Latency (the percentile is part of the name)
    "REQ_INSERT_LATENCY_AVG": "Insert latency, average (ms)",
    "REQ_INSERT_LATENCY_P99": "Insert latency, P99 (ms)",
    "REQ_UPSERT_LATENCY_AVG": "Upsert latency, average (ms)",
    "REQ_UPSERT_LATENCY_P99": "Upsert latency, P99 (ms)",
    "REQ_DELETE_LATENCY_AVG": "Delete latency, average (ms)",
    "REQ_DELETE_LATENCY_P99": "Delete latency, P99 (ms)",
    "REQ_SEARCH_LATENCY_AVG": "Search latency, average (ms)",
    "REQ_SEARCH_LATENCY_P99": "Search latency, P99 (ms)",
    "REQ_QUERY_LATENCY_AVG": "Query latency, average (ms)",
    "REQ_QUERY_LATENCY_P99": "Query latency, P99 (ms)",
    # Failure rate (there is no overall success/fail rate; query per operation)
    "REQ_FAIL_RATE_INSERT": "Failed insert requests (percent)",
    "REQ_FAIL_RATE_BULK_INSERT": "Failed bulk insert requests (percent)",
    "REQ_FAIL_RATE_UPSERT": "Failed upsert requests (percent)",
    "REQ_FAIL_RATE_DELETE": "Failed delete requests (percent)",
    "REQ_FAIL_RATE_SEARCH": "Failed search requests (percent)",
    "REQ_FAIL_RATE_QUERY": "Failed query requests (percent)",
    # Data
    "ENTITIES_COUNT": "Total entities (count)",
    "ENTITIES_LOADED": "Loaded entities (count)",
    "ENTITIES_INDEXED": "Indexed entities (count)",
    "COLLECTIONS_COUNT": "Collections (count)",
    "UNLOADED_COLLECTIONS_COUNT": "Unloaded collections (count)",
    "FLUSH_COUNT": "Flush operations per minute (count/m)",
}

# Names that look plausible (and appeared in older docs) but are rejected by the API.
REPLACEMENTS: Dict[str, str] = {
    "REQ_SUCCESS_RATE": "There is no overall success rate. Use REQ_FAIL_RATE_<OP> per operation "
                        "(e.g. REQ_FAIL_RATE_SEARCH); success rate = 100 - fail rate.",
    "REQ_FAIL_RATE": "There is no overall fail rate. Use REQ_FAIL_RATE_<OP> per operation, "
                     "e.g. REQ_FAIL_RATE_SEARCH, REQ_FAIL_RATE_QUERY, REQ_FAIL_RATE_INSERT.",
    "ENTITIES_INSERT_RATE": "Use VECTOR_REQ_INSERT_COUNT (vectors inserted per second).",
    "REQ_BULK_INSERT_LATENCY_P99": "Bulk insert latency is not available. Use REQ_BULK_INSERT_COUNT "
                                   "and REQ_FAIL_RATE_BULK_INSERT.",
}

DEFAULT_STAT = "AVG"


def _invalid(message: str, expected: str, got: Any, fix: str) -> StructuredToolError:
    """INVALID_ARGUMENT error for metric_queries. The full list of valid values goes in
    'expected' so it is never cut by the message length limit."""
    return StructuredToolError({
        "error": "INVALID_ARGUMENT",
        "message": message,
        "field": "metric_queries",
        "expected": expected,
        "got": got,
        "fix": fix,
    })


VALID_NAMES = "Valid metric names: " + ", ".join(METRICS)


def allowed_stats(name: str) -> List[str]:
    """Stats accepted for a metric.

    The API treats 'stat' as deprecated: every result comes back as the
    per-bucket value of the named metric (the response always echoes AVG).
    The percentile of a latency metric is chosen by its name, so the only
    accepted values are AVG, plus P99 for *_LATENCY_P99 for compatibility.
    """
    if name.endswith("_LATENCY_P99"):
        return ["AVG", "P99"]
    return ["AVG"]


def validate_metric_queries(metric_queries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Validate and normalize metric queries. Raises ValueError with valid choices."""
    if not metric_queries:
        raise _invalid("metric_queries is empty.", VALID_NAMES, metric_queries,
                       'Pass at least one item like {"metricName": "REQ_SEARCH_COUNT"}.')
    out = []
    for q in metric_queries:
        if not isinstance(q, dict) or "metricName" not in q:
            raise _invalid("Each metric query must be an object with 'metricName' (and optional 'stat').",
                           '[{"metricName": "<METRIC_NAME>", "stat": "AVG"}]. ' + VALID_NAMES, q,
                           'Use e.g. {"metricName": "REQ_SEARCH_LATENCY_P99"}.')
        name = str(q["metricName"]).strip().upper()
        if name not in METRICS:
            fix = REPLACEMENTS.get(name, "Pick a name from 'expected'.")
            raise _invalid(f"Unknown metric name '{q['metricName']}'.", VALID_NAMES, q["metricName"], fix)
        stat = str(q.get("stat") or DEFAULT_STAT).strip().upper()
        valid = allowed_stats(name)
        if stat not in valid:
            fix = "Omit stat or use AVG."
            if "_LATENCY_" in name or stat in ("P99", "P90"):
                fix += (" For latency percentiles pick the metric by name instead, e.g. "
                        "REQ_SEARCH_LATENCY_P99 or REQ_SEARCH_LATENCY_AVG.")
            raise _invalid(f"stat '{q.get('stat')}' is not valid for {name}.",
                           f"Valid stat values for {name}: {', '.join(valid)} (or omit stat)",
                           q.get("stat"), fix)
        out.append({"name": name, "stat": stat})
    return out


def paired_count_metric(name: str) -> Optional[str]:
    """Request-count metric whose traffic explains nulls in a latency / fail-rate metric."""
    for op in _OPS:
        if name == f"REQ_FAIL_RATE_{op}" or name.startswith(f"REQ_{op}_LATENCY_"):
            count = f"REQ_{op}_COUNT"
            return count if count in METRICS else None
    return None


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


NULL_NOTE = ("value=null means the API reported no data point for that time bucket. It is NOT "
             "the same as 0. Null buckets are listed in 'null_runs' with their status.")
NULL_NOTE_UNEXPLAINED = (
    "value=null means no data point was reported for that bucket. It is not 0, and on its own it "
    "does not show that the operation was unused or the cluster idle: with granularity coarser "
    "than PT2M, buckets of windows that did have traffic are often null as well. Confirm with a "
    "fine granularity (PT30S) over a short recent window before concluding there was no activity. "
    "Other causes: the cluster was not running yet, or the operation had not been used yet. If a "
    "resource metric such as CU_COMPUTATION is also null at PT30S for the same window, the "
    "cluster was not reporting metrics then.")


def annotate(results: List[Dict[str, Any]], counts: Dict[str, Dict[str, Optional[float]]]) -> None:
    """Add value_status to every point and a null_note to results that contain nulls.

    counts: metric name -> {timestamp: numeric value or None} for paired request-count metrics.
    value_status values:
      - "reported": the API returned a value (it may legitimately be "0").
      - "unknown_or_no_failures": fail-rate is null while requests were served in that bucket.
        Usually this means nothing failed, but the fail-rate series alone cannot prove it.
      - "no_requests": latency / fail-rate is null and the paired request count is 0.
      - "no_data": no data point reported; cause cannot be determined from this metric alone.
    """
    for res in results:
        name = res.get("name", "")
        values = res.get("values") or []
        pair = paired_count_metric(name)
        pair_series = counts.get(pair) if pair else None
        nulls = 0
        for point in values:
            if point.get("value") is not None:
                point["value_status"] = "reported"
                continue
            nulls += 1
            status = "no_data"
            if pair_series is not None and point.get("timestamp") in pair_series:
                c = pair_series[point["timestamp"]]
                if c == 0:
                    status = "no_requests"
                elif c is not None and name.startswith("REQ_FAIL_RATE_"):
                    status = "unknown_or_no_failures"
            point["value_status"] = status
        if nulls:
            res["null_points"] = nulls
            if pair_series is not None:
                res["null_note"] = (
                    NULL_NOTE + f" Statuses were derived from {pair} for the same window: "
                    "'unknown_or_no_failures' = requests were served but no failure data was reported; "
                    "this usually means no request failed, but the metric itself cannot confirm it, so "
                    "say so rather than stating 0%; "
                    "'no_requests' = the request count was 0 in that bucket; "
                    f"'no_data' = neither this metric nor {pair} reported a point (e.g. the operation "
                    "was not used then, or coarse buckets hid it; confirm at PT30S).")
            else:
                res["null_note"] = NULL_NOTE_UNEXPLAINED


def compact(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Output form of annotated results: 'values' keeps only points that have a value, and null
    buckets become 'null_runs' ({status, from, to, points} per run of consecutive nulls with the
    same status). Per-point status labels were about a third of the result and most of a sparse
    series; runs keep the null-is-not-0 information in a few entries. 'buckets' is the number of
    buckets in the series, so values + null_runs account for all of them.
    """
    out = []
    for res in results:
        values = res.get("values") or []
        kept, runs, cur = [], [], None
        for p in values:
            if p.get("value") is not None:
                kept.append({k: v for k, v in p.items() if k != "value_status"})
                cur = None
                continue
            status = p.get("value_status", "no_data")
            if cur is not None and cur["status"] == status:
                cur["to"] = p.get("timestamp")
                cur["points"] += 1
            else:
                cur = {"status": status, "from": p.get("timestamp"), "to": p.get("timestamp"), "points": 1}
                runs.append(cur)
        r = {k: v for k, v in res.items() if k not in ("values", "null_points", "null_note")}
        r["buckets"] = len(values)
        r["values"] = kept
        if runs:
            r["null_points"] = sum(x["points"] for x in runs)
            r["null_runs"] = runs
            if res.get("null_note"):
                r["null_note"] = res["null_note"]
        out.append(r)
    return out


def fit_results(results: List[Dict[str, Any]], budget: int = RESULT_BUDGET):
    """(compacted results within budget bytes of JSON, trim info or None).

    When the compacted result is still too large, every series keeps its most recent N buckets
    (the same N for all, so timestamps stay aligned) with N as large as fits. Most recent rather
    than downsampled: downsampling drops or merges buckets, which is the coarse-granularity
    problem again (hidden spikes, gaps read as zero), while a recent tail is exact and the older
    part is one start/end re-query.
    """
    full = compact(results)
    if len(json.dumps({"results": full})) <= budget:
        return full, None
    longest = max((len(r.get("values") or []) for r in results), default=0)

    def tail(n):
        return compact([{**r, "values": (r.get("values") or [])[-n:]} for r in results])

    lo, hi, best = 1, max(1, longest - 1), tail(1)
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = tail(mid)
        if len(json.dumps({"results": cand})) <= budget:
            best, lo = cand, mid + 1
        else:
            hi = mid - 1
    kept_n = max(r["buckets"] for r in best) if best else 0
    firsts = [(r.get("values") or [])[0].get("timestamp") for r in results if r.get("values")]
    kept_firsts = [(r.get("values") or [])[-kept_n].get("timestamp") for r in results
                   if len(r.get("values") or []) >= kept_n > 0]
    return best, {"kept": kept_n, "total": longest, "bytes_total": len(json.dumps({"results": full})),
                  "window_start": min(firsts) if firsts else None,
                  "kept_from": min(kept_firsts) if kept_firsts else None}


def trim_hints(info: Dict[str, Any], cluster_id: str, metric_queries: List[Dict[str, str]],
               granularity: str):
    """(step, note) telling the model what fit_results cut and how to get the rest.

    The re-query uses end = first kept bucket. Observed: the metrics API treats end as exclusive and
    lays buckets on the start's grid, so the re-query's last bucket is the one just before the kept
    part (no overlap, no gap) when it starts at the original window start.
    """
    note = (f"Values trimmed to fit the response size budget: each series shows its most recent "
            f"{info['kept']} of {info['total']} buckets (from {info['kept_from']}); the full result was "
            f"{info['bytes_total']:,} bytes of JSON and clients truncate long tool output. The per-series "
            f"summary covers the whole window. For older buckets re-query the earlier part (see next_steps) "
            f"or query fewer series.")
    st = None
    if info.get("window_start") and info.get("kept_from"):
        st = step("query_cluster_metrics", "Older buckets that were trimmed from this result.",
                  cluster_id=cluster_id, metric_queries=metric_queries, granularity=granularity,
                  start=info["window_start"], end=info["kept_from"])
    return st, note


def needed_count_metrics(results: List[Dict[str, Any]], already: Dict[str, Any]) -> List[str]:
    """Paired count metrics needed to explain nulls and not already in the response."""
    need = []
    for res in results:
        if not any(p.get("value") is None for p in res.get("values") or []):
            continue
        pair = paired_count_metric(res.get("name", ""))
        if pair and pair not in already and pair not in need:
            need.append(pair)
    return need


def series_by_timestamp(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[float]]]:
    return {r.get("name", ""): {p.get("timestamp"): _num(p.get("value")) for p in r.get("values") or []}
            for r in results}


def api_error_fix(names: List[str]) -> Optional[str]:
    """Extra fix text for a server-side rejection of these metric names, if any applies."""
    if any(n in ("READ_VCU", "WRITE_VCU") for n in names):
        return ("READ_VCU / WRITE_VCU are only available on Serverless clusters; Dedicated clusters "
                "reject them. Remove them, or use CU_COMPUTATION / CU_CAPACITY on Dedicated clusters.")
    return None


# --- granularity / coverage ----------------------------------------------------

# Buckets per series per request. Observed: 28,800 accepted, 40,320 rejected (error 20011).
MAX_POINTS = 25000
# Points (all series together) that a suggested re-query may return so the model can read the
# whole result: the shared response budget divided by ~100 bytes per point (observed 86-91 bytes
# per point including value_status).
READABLE_POINTS = RESULT_BUDGET // 100
# Finer-to-coarser granularities to suggest when re-querying.
GRANULARITY_LADDER = ["PT30S", "PT1M", "PT2M", "PT5M", "PT10M", "PT15M", "PT30M", "PT1H", "P1D"]
# Below this share of buckets with a value, a coarse query is treated as possibly under-sampled.
LOW_COVERAGE = 0.5

_DUR_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def duration_seconds(iso: Optional[str]) -> Optional[int]:
    """Seconds in an ISO 8601 duration with D/H/M/S parts (the units the API accepts)."""
    m = _DUR_RE.match(str(iso or "").strip().upper())
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def window_seconds(period: Optional[str], start: Optional[str], end: Optional[str]) -> Optional[int]:
    if period:
        return duration_seconds(period)
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return int((b - a).total_seconds())
    except (TypeError, ValueError):
        return None


def finest_granularity(window_s: int) -> str:
    """Finest granularity whose bucket count for this window stays under MAX_POINTS."""
    for g in GRANULARITY_LADDER:
        if window_s / duration_seconds(g) <= MAX_POINTS:
            return g
    return GRANULARITY_LADDER[-1]


def _iso(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"P{seconds // 86400}D"
    if seconds % 3600 == 0:
        return f"PT{seconds // 3600}H"
    return f"PT{max(1, seconds // 60)}M"


def _readable_period(granularity: str, n_series: int, cap_s: int) -> Optional[str]:
    """Longest whole-hour period at this granularity whose points (all series) stay readable."""
    secs = min(cap_s, duration_seconds(granularity) * (READABLE_POINTS // max(1, n_series)))
    secs = (secs // 3600) * 3600
    return _iso(secs) if secs > 0 else None


GAUGE_PREFIXES = ("CU_", "STORAGE_", "CLUSTER_WRITE_CAPACITY", "ENTITIES_")


FAIL_RATE_CAVEAT = (
    "REQ_FAIL_RATE_* may not count requests rejected by rate limiting or write quotas (open-source "
    "Milvus rejects them before the request handler), so 0% does not prove nothing was rejected; check "
    "client-side errors. Buckets average their interval, so brief errors look smaller, longer and later: "
    "time short incidents from client logs."
)

# Configuration-like series that report a value in every bucket regardless of sampling; they say
# nothing about whether a coarse query lost data, so coverage is judged without them.
ALWAYS_REPORTED = ("CU_SIZE", "REPLICA_COUNT")


def fail_rate_caveat(results: List[Dict[str, Any]]) -> Optional[str]:
    """One note for any result that contains a REQ_FAIL_RATE_* series."""
    if any(str(r.get("name", "")).startswith("REQ_FAIL_RATE_") for r in results or []):
        return FAIL_RATE_CAVEAT
    return None


def suspect_zero_buckets(r: Dict[str, Any], granularity: Optional[str]) -> int:
    """Zero-valued buckets of a gauge series that look unsampled rather than real.

    Observed at coarse granularity: CU_CAPACITY at P7D/PT1H returned "0" in 167 of 168 buckets
    and 13.11 in the last, while PT1M showed ~14.5% throughout. A gauge (CU, storage, entities)
    that is mostly 0 with some non-zero values at a granularity coarser than PT2M is treated as
    under-sampled.
    """
    g_s = duration_seconds(granularity)
    if not g_s or g_s <= 120 or not str(r.get("name", "")).startswith(GAUGE_PREFIXES):
        return 0
    nums = [_num(p.get("value")) for p in r.get("values") or [] if p.get("value") is not None]
    zeros = sum(1 for v in nums if v == 0)
    if zeros and zeros < len(nums) and zeros * 2 >= len(nums):
        return zeros
    return 0


def series_summary(results: List[Dict[str, Any]], granularity: Optional[str] = None) -> Optional[str]:
    """One-line per-series summary (buckets with a value, first/last such timestamp, max).

    Goes into notes, which are emitted before data, so it survives client-side truncation of
    long results. None when every bucket of every series has a value.
    """
    parts = []
    any_null = False
    for r in results:
        values = r.get("values") or []
        got = [(p.get("timestamp"), _num(p.get("value"))) for p in values if p.get("value") is not None]
        any_null |= len(got) < len(values)
        s = f"{r.get('name')}: {len(got)}/{len(values)} buckets with a value"
        if got:
            nums = [v for _, v in got if v is not None]
            s += f", first {got[0][0]}, last {got[-1][0]}"
            if nums:
                s += f", max {max(nums):g}"
        zeros = suspect_zero_buckets(r, granularity)
        if zeros:
            any_null = True
            s += (f" ({zeros} of them report 0 next to non-zero values; at {granularity} such zeros "
                  f"are likely unsampled, NOT 0%; check at PT30S/PT1M)")
        parts.append(s)
    if not parts or not any_null:
        return None
    return "Per series: " + "; ".join(parts) + "."


SPARSE_NOTE = (
    "Few or no buckets have a value at granularity {g}. At coarse granularities, windows that have "
    "values at PT30S are often reported as null, so a null here does NOT mean no traffic or 0%. "
    "Re-query a shorter window with fine buckets (see next_steps) before concluding there was no "
    "activity.")


def coverage_hints(results: List[Dict[str, Any]], cluster_id: str, metric_queries: List[Dict[str, str]],
                   granularity: str, period: Optional[str], start: Optional[str], end: Optional[str]):
    """(steps, notes) when a coarse query looks under-sampled. Empty when coverage is fine."""
    g_s = duration_seconds(granularity)
    win = window_seconds(period, start, end)
    # PT2M and finer were observed to keep sparse data; only coarser queries are checked.
    if not g_s or not win or g_s <= 120:
        return [], []
    total = reported = 0
    # Latency / fail-rate are legitimately null without requests (see value_status); judge sampling
    # on the other series when there are any.
    base = [r for r in results if not paired_count_metric(r.get("name", ""))
            and r.get("name") not in ALWAYS_REPORTED] or results
    for r in base:
        zeros = suspect_zero_buckets(r, granularity)
        for p in r.get("values") or []:
            total += 1
            reported += p.get("value") is not None
        reported -= zeros
    if total == 0 or reported / total >= LOW_COVERAGE:
        return [], []
    steps: List[Dict[str, Any]] = []
    # Suggestions are sized to stay readable (READABLE_POINTS over all series), not to the API's
    # per-request maximum: a result the client truncates does not help.
    n = max(1, len(metric_queries or results))
    for g, why in (("PT30S", "Recent window at PT30S, sized so the whole result stays readable."),
                   ("PT2M", "Longer recent window at PT2M (sparse traffic was still visible at PT2M), "
                            "sized to stay readable.")):
        p = _readable_period(g, n, win)
        if p and duration_seconds(g) < g_s:
            when: Dict[str, Any] = {"period": p}
            if start and end and not period:  # keep an explicit window: its last part
                try:
                    b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                    a = b.timestamp() - duration_seconds(p)
                    when = {"start": datetime.fromtimestamp(a, b.tzinfo).isoformat().replace("+00:00", "Z"),
                            "end": end}
                except (TypeError, ValueError):
                    pass
            steps.append(step("query_cluster_metrics", why, cluster_id=cluster_id, **when,
                              granularity=g, metric_queries=metric_queries))
    return steps, [SPARSE_NOTE.format(g=granularity) + f" ({reported}/{total} buckets have a value.)"]
