"""get_cluster_activity_history: which days in a long window had requests, without coarse-bucket nulls.

Coarse granularities (P1D, and PT1H over windows longer than a day) were observed to return null
buckets for windows that do have values at fine granularity, so a 6-month query at P1D cannot tell
"no traffic" from "not sampled". This tool reads the window in 7-day chunks at PT5M (a size the API
accepts) and returns a compact per-day summary instead of the raw points.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from zilliz_mcp_server.app import read_tool
from zilliz_mcp_server.common import hints, openapi_client
from zilliz_mcp_server.common.budget import RESULT_BUDGET
from zilliz_mcp_server.common.hints import step

logger = logging.getLogger(__name__)

DEFAULT_METRICS = ["REQ_SEARCH_COUNT", "REQ_QUERY_COUNT", "REQ_INSERT_COUNT", "REQ_UPSERT_COUNT",
                   "REQ_DELETE_COUNT"]
MAX_DAYS = 180
CHUNK_DAYS = 7
GRANULARITY = "PT5M"
MAX_CONCURRENCY = 4
TOTAL_TIMEOUT_S = 90
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _parse(ts: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.strptime(str(ts), _FMT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def chunks(start: datetime, end: datetime, days: int = CHUNK_DAYS) -> List[Tuple[datetime, datetime]]:
    out, s = [], start
    while s < end:
        e = min(s + timedelta(days=days), end)
        out.append((s, e))
        s = e
    return out


def _num(v: Any) -> Optional[float]:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def summarize(results_by_chunk: List[List[Dict[str, Any]]], metrics: List[str]) -> Dict[str, Any]:
    """Per metric: active days (any bucket > 0) with that day's peak, first/last active timestamp."""
    per: Dict[str, Dict[str, Any]] = {m: {"days": {}, "first": None, "last": None, "max": None,
                                         "reported": 0, "seen": set()} for m in metrics}
    for results in results_by_chunk:
        for r in results or []:
            m = per.get(r.get("name"))
            if m is None:
                continue
            for p in r.get("values") or []:
                v = _num(p.get("value"))
                if v is None:
                    continue
                ts = p.get("timestamp") or ""
                if ts in m["seen"]:  # adjacent chunks can both return the boundary bucket
                    continue
                m["seen"].add(ts)
                m["reported"] += 1
                if v <= 0:
                    continue
                day = ts[:10]
                m["days"][day] = max(m["days"].get(day, 0.0), v)
                m["first"] = ts if m["first"] is None or ts < m["first"] else m["first"]
                m["last"] = ts if m["last"] is None or ts > m["last"] else m["last"]
                m["max"] = v if m["max"] is None else max(m["max"], v)
    out = {}
    for name, m in per.items():
        out[name] = {"active_days": len(m["days"]), "first_active": m["first"], "last_active": m["last"],
                     "peak": m["max"], "buckets_with_value": m["reported"],
                     "peak_by_day": {d: round(v, 3) for d, v in sorted(m["days"].items())}}
    return out


def fit(report: Dict[str, Any], budget: int = RESULT_BUDGET) -> Optional[str]:
    """Collapse per-day peaks to per-week peaks if the report exceeds the size budget."""
    if len(json.dumps(report)) <= budget:
        return None
    for m in report["metrics"].values():
        weeks: Dict[str, float] = {}
        for d, v in m.pop("peak_by_day").items():
            day = datetime.strptime(d, "%Y-%m-%d")
            wk = (day - timedelta(days=day.weekday())).strftime("%Y-%m-%d")
            weeks[wk] = max(weeks.get(wk, 0.0), v)
        m["peak_by_week"] = weeks
    return "Per-day peaks were collapsed to weeks (keyed by Monday) to keep the result readable."


def build_hints(report: Dict[str, Any], cluster_id: str, failed: List[str]):
    notes, steps = [], []
    active = {n: m for n, m in report["metrics"].items() if m["active_days"]}
    if active:
        days = sorted({d for m in active.values() for d in (m.get("peak_by_day") or m.get("peak_by_week") or {})})
        first = min(m["first_active"] for m in active.values())
        last = max(m["last_active"] for m in active.values())
        peaks = ", ".join("%s peak %g" % (n, m["peak"]) for n, m in active.items())
        notes.append(f"Requests seen on {len(days)} day(s)/week(s) between {report['window_start']} and "
                     f"{report['window_end']}: first {first}, last {last} ({peaks}).")
        lt = _parse(last)
        if lt:
            steps.append(step("query_cluster_metrics", "Look at the most recent active period in detail.",
                              cluster_id=cluster_id, start=(lt - timedelta(hours=2)).strftime(_FMT),
                              end=min(lt + timedelta(hours=1), datetime.now(timezone.utc)).strftime(_FMT),
                              granularity="PT1M",
                              metric_queries=[{"metricName": n} for n in active][:3]))
    else:
        notes.append(f"No request metric was above 0 in any {GRANULARITY} bucket between "
                     f"{report['window_start']} and {report['window_end']}"
                     + ("." if not failed else " (for the chunks that could be read)."))
    if failed:
        notes.append(f"{len(failed)} of {report['chunks']} chunks could not be read, so those periods are "
                     f"unknown: {'; '.join(failed[:4])}{' …' if len(failed) > 4 else ''}. Re-run, or query "
                     f"them with query_cluster_metrics at {GRANULARITY}.")
    return steps, notes


@read_tool()
async def get_cluster_activity_history(cluster_id: str, days: int = 180,
                                       metrics: Optional[List[str]] = None) -> str:
    """
    Which days in the last N days (max 180) had requests on a cluster, as a compact summary.

    Use this for long-range questions such as "has there been traffic in the past 6 months" or
    "since when does this cluster get queries". query_cluster_metrics at coarse granularity (P1D,
    PT1H over long windows) often returns null even for periods that had requests; this tool reads
    the window at PT5M in 7-day chunks (a few seconds to ~30 s for 180 days) and returns only the
    summary, not raw points.

    Args:
        cluster_id: ID of the cluster.
        days: Window length in days, 1-180 (default 180). The window starts no earlier than the
            cluster's creation time.
        metrics: Request-count metric names to check (default: REQ_SEARCH_COUNT, REQ_QUERY_COUNT,
            REQ_INSERT_COUNT, REQ_UPSERT_COUNT, REQ_DELETE_COUNT).

    Returns:
        JSON {"notes": [...], "next_steps": [...], "data": {...}}. data: window_start, window_end,
        granularity, chunks, failed_chunks, and per metric: active_days (days with any bucket > 0),
        first_active, last_active, peak (highest bucket value, requests per second), buckets_with_value,
        peak_by_day {"YYYY-MM-DD": peak} (or peak_by_week when the window has too many active days).
    """
    ctx = {"cluster_id": cluster_id, "days": days}
    try:
        if not isinstance(days, int) or not 1 <= days <= MAX_DAYS:
            raise ValueError(f"days must be an integer from 1 to {MAX_DAYS}, got {days!r}.")
        names = [str(m).strip().upper() for m in (metrics or DEFAULT_METRICS)]
        bad = [n for n in names if not (n.startswith(("REQ_", "VECTOR_REQ_")) and n.endswith("_COUNT"))]
        if bad:
            raise ValueError("metrics must be request-count metrics (REQ_*_COUNT or VECTOR_REQ_*_COUNT); "
                             f"got {bad}.")
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(days=days)
        cluster = (openapi_client.control_plane_api_request(f"/v2/clusters/{cluster_id}").get("data") or {})
        created = _parse(cluster.get("createTime"))
        if created and created > start:
            start = created.replace(second=0, microsecond=0)
        parts = chunks(start, now)
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

        async def fetch(s: datetime, e: datetime):
            body = {"start": s.strftime(_FMT), "end": e.strftime(_FMT), "granularity": GRANULARITY,
                    "metricQueries": [{"name": n, "stat": "AVG"} for n in names]}
            async with sem:
                resp = await asyncio.to_thread(openapi_client.control_plane_api_request,
                                               f"/v2/clusters/{cluster_id}/metrics/query",
                                               body_map=body, method="POST")
            return (resp.get("data") or {}).get("results") or []

        tasks = [asyncio.ensure_future(fetch(s, e)) for s, e in parts]
        done, pending = await asyncio.wait(tasks, timeout=TOTAL_TIMEOUT_S)
        for t in pending:
            t.cancel()
        got, failed = [], []
        for (s, e), t in zip(parts, tasks):
            if t in done and not t.cancelled() and t.exception() is None:
                got.append(t.result())
            else:
                why = "timed out" if t in pending else str(t.exception())[:80]
                failed.append(f"{s:%Y-%m-%d}..{e:%Y-%m-%d} ({why})")
        if parts and not got:
            first_err = next((t.exception() for t in tasks if t in done and not t.cancelled() and t.exception()),
                             None)
            if first_err:
                raise first_err
            raise TimeoutError(f"none of the {len(parts)} metric chunks finished within {TOTAL_TIMEOUT_S}s; "
                               "activity is unknown. Retry with fewer days.")
        report: Dict[str, Any] = {"window_start": start.strftime(_FMT), "window_end": now.strftime(_FMT),
                                  "granularity": GRANULARITY, "chunks": len(parts),
                                  "failed_chunks": len(failed), "metrics": summarize(got, names)}
        collapsed = fit(report)
        steps, notes = build_hints(report, cluster_id, failed)
        if collapsed:
            notes.append(collapsed)
        return hints.ok(report, steps, notes)
    except Exception as e:
        logger.error(f"GET_CLUSTER_ACTIVITY_HISTORY ERROR: {e}")
        raise hints.tool_error("get_cluster_activity_history", e, ctx) from e
