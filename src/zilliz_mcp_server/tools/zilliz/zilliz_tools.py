"""Zilliz Control Plane tools."""

import json
import logging
from typing import Dict, Any, List, Optional, Union
from pydantic import StrictBool
from zilliz_mcp_server.common import openapi_client
from zilliz_mcp_server.common import hints
from zilliz_mcp_server.common import next_steps as ns
from zilliz_mcp_server.common.budget import RESULT_BUDGET
from zilliz_mcp_server.settings import config
from zilliz_mcp_server.app import zilliz_mcp, read_tool, write_tool
from zilliz_mcp_server.tools.zilliz import metrics as metrics_catalog

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

SUSPEND_IMPACT = (
    "Suspending stops the cluster from serving: all reads, writes and searches fail until "
    "resume_cluster is called, and resuming takes several minutes. Compute billing stops; "
    "storage is still billed."
)

@read_tool()
async def list_projects() -> str:
    """
    List all projects scoped to API Key in Zilliz Cloud.
    
    Args:
        None
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        JSON string containing the API response with projects data
        Example:
        '[{"project_name": "Default Project", "project_id": "proj-f5b02814db7ccfe2d16293", "instance_count": 0, "create_time": "2023-06-14T06:59:07Z"}]'
        
    """
    try:
        # Log request
        logger.info("LIST_PROJECTS: fetching all projects")
        
        response = openapi_client.control_plane_api_request("/v2/projects")
        projects = response.get('data', [])
        
        # Format project information
        formatted_projects = []
        for project in projects:
            project_info = {
                'project_name': project.get('projectName', 'Unknown'),
                'project_id': project.get('projectId', 'Unknown'),
                'instance_count': project.get('instanceCount', 0),
                'create_time': project.get('createTime', 'Unknown')
            }
            formatted_projects.append(project_info)
        
        # Log results
        logger.info(f"LIST_PROJECTS RESULT: found {len(formatted_projects)} projects")
        
        return hints.ok(formatted_projects, *ns.list_projects(formatted_projects))
        
    except Exception as e:
        logger.error(f"LIST_PROJECTS ERROR: {str(e)}")
        raise hints.tool_error("list_projects", e) from e


@read_tool()
async def list_clusters(page_size: int = 10, current_page: int = 1) -> str:
    """
    List all clusters scoped to API Key in Zilliz Cloud.
    If you want to list all clusters, you can set page_size to 100 and current_page to 1.
    
    Args:
        page_size: The number of records to include in each response (default: 10, range 1-100)
        current_page: The current page number (default: 1)
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        List containing cluster data
        Example:
        [
            {
                "cluster_id": "inxx-xxxxxxxxxxxxxxx",
                "cluster_name": "dedicated-3",
                "description": "",
                "region_id": "aws-us-west-2",
                "plan": "Standard",
                "cu_type": "Performance-optimized",
                "cu_size": 1,
                "status": "RUNNING",
                "connect_address": "https://inxx-xxxxxxxxxxxxxxx.aws-us-west-2.vectordb.zillizcloud.com:19530",
                "private_link_address": "",
                "project_id": "proj-xxxxxxxxxxxxxxxxxxxxxx",
                "create_time": "2024-06-30T16:49:50Z"
            }
        ]
        
    """
    try:
        # Log request
        logger.info(f"LIST_CLUSTERS: page_size={page_size}, current_page={current_page}")
        
        # Build query parameters
        params = {
            'pageSize': page_size,
            'currentPage': current_page
        }
        
        response = openapi_client.control_plane_api_request("/v2/clusters", params_map=params)
        clusters_data = response.get('data', {})
        clusters = clusters_data.get('clusters', [])
        
        # Format cluster information
        formatted_clusters = []
        for cluster in clusters:
            cluster_info = {
                'cluster_id': cluster.get('clusterId', 'Unknown'),
                'cluster_name': cluster.get('clusterName', 'Unknown'),
                'description': cluster.get('description', ''),
                'region_id': cluster.get('regionId', 'Unknown'),
                'plan': cluster.get('plan', 'Unknown'),
                'cu_type': cluster.get('cuType', ''),
                'cu_size': cluster.get('cuSize', 0),
                'status': cluster.get('status', 'Unknown'),
                'connect_address': cluster.get('connectAddress', ''),
                'private_link_address': cluster.get('privateLinkAddress', ''),
                'project_id': cluster.get('projectId', 'Unknown'),
                'create_time': cluster.get('createTime', 'Unknown')
            }
            formatted_clusters.append(cluster_info)
        
        # Log results
        logger.info(f"LIST_CLUSTERS RESULT: found {len(formatted_clusters)} clusters")
        
        return hints.ok(formatted_clusters, *ns.list_clusters(formatted_clusters, page_size, current_page))
        
    except Exception as e:
        logger.error(f"LIST_CLUSTERS ERROR: {str(e)}")
        raise hints.tool_error("list_clusters", e) from e

@write_tool(destructive=False)
async def create_free_cluster(cluster_name: str, project_id: str) -> str:
    """
    Create a free cluster in Zilliz Cloud. This creates a new resource; only call it when
    the user asks for a new cluster. Each organization has a limited free-cluster quota,
    so the call can fail when it is used up. Get project_id from list_projects.

    Args:
        cluster_name: Name of the cluster to create
        project_id: ID of the project to which the cluster belongs
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        Dict containing cluster creation info
        Example:
        {
            "cluster_id": "inxx-xxxxxxxxxxxxxxx",
            "username": "db_xxxxxxxx",
            "prompt": "successfully submitted, cluster is being created..."
        }
        
    """
    try:
        # Log request
        logger.info(f"CREATE_FREE_CLUSTER: cluster_name={cluster_name}, project_id={project_id}")
        
        # Get free cluster region_id from config
        region_id = config.free_cluster_region
        
        # Build request body
        body = {
            'clusterName': cluster_name,
            'projectId': project_id,
            'regionId': region_id
        }
        
        response = openapi_client.control_plane_api_request(
            "/v2/clusters/createFree", 
            body_map=body, 
            method="POST"
        )
        
        # Extract and format the response data
        data = response.get('data', {})
        cluster_info = {
            'cluster_id': data.get('clusterId', 'Unknown'),
            'username': data.get('username', 'Unknown'),
            'prompt': data.get('prompt', 'Unknown'),
        }
        
        # Log results
        logger.info(f"CREATE_FREE_CLUSTER RESULT: cluster_id={cluster_info['cluster_id']}")
        
        return hints.ok(cluster_info, *ns.create_free_cluster(cluster_info))
        
    except Exception as e:
        logger.error(f"CREATE_FREE_CLUSTER ERROR: {str(e)}")
        raise hints.tool_error("create_free_cluster", e, {"project_id": project_id}) from e

@read_tool()
async def describe_cluster(cluster_id: str) -> str:
    """
    Describe a cluster in detail.
    
    Args:
        cluster_id: ID of the cluster whose details are to return
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        Dict containing detailed cluster information
        Example:
        {
            "cluster_id": "inxx-xxxxxxxxxxxxxxx",
            "cluster_name": "Free-01",
            "project_id": "proj-b44a39b0c51cf21791a841",
            "description": "",
            "region_id": "gcp-us-west1",
            "cu_type": "",
            "plan": "Free",
            "status": "RUNNING",
            "connect_address": "https://inxx-xxxxxxxxxxxxxxx.api.gcp-us-west1.zillizcloud.com",
            "private_link_address": "",
            "cu_size": 0,
            "storage_size": 0,
            "snapshot_number": 0,
            "create_progress": 100,
            "create_time": "2024-06-24T12:35:09Z"
        }
        
    """
    try:
        # Log request
        logger.info(f"DESCRIBE_CLUSTER: cluster_id={cluster_id}")
        
        # Build URI with cluster_id as path parameter
        uri = f"/v2/clusters/{cluster_id}"
        
        response = openapi_client.control_plane_api_request(uri, method="GET")
        
        # Extract and format the response data
        data = response.get('data', {})
        cluster_info = {
            'cluster_id': data.get('clusterId', 'Unknown'),
            'cluster_name': data.get('clusterName', 'Unknown'),
            'project_id': data.get('projectId', 'Unknown'),
            'description': data.get('description', ''),
            'region_id': data.get('regionId', 'Unknown'),
            'cu_type': data.get('cuType', ''),
            'plan': data.get('plan', 'Unknown'),
            'status': data.get('status', 'Unknown'),
            'connect_address': data.get('connectAddress', ''),
            'private_link_address': data.get('privateLinkAddress', ''),
            'cu_size': data.get('cuSize', 0),
            'storage_size': data.get('storageSize', 0),
            'snapshot_number': data.get('snapshotNumber', 0),
            'create_progress': data.get('createProgress', 0),
            'create_time': data.get('createTime', 'Unknown')
        }
        
        # Log results
        logger.info(f"DESCRIBE_CLUSTER RESULT: name={cluster_info['cluster_name']}, status={cluster_info['status']}")
        
        return hints.ok(cluster_info, *ns.describe_cluster(cluster_info))
        
    except Exception as e:
        logger.error(f"DESCRIBE_CLUSTER ERROR: {str(e)}")
        raise hints.tool_error("describe_cluster", e, {"cluster_id": cluster_id}) from e

@write_tool(destructive=True, idempotent=True)
async def suspend_cluster(cluster_id: str, confirm: StrictBool = False) -> str:
    """
    Suspend a dedicated cluster in Zilliz Cloud. DESTRUCTIVE TO AVAILABILITY: once
    suspended, the cluster rejects all reads and writes until resume_cluster is called,
    and resuming takes several minutes. Compute billing stops; storage is still billed.
    Only call this when the user explicitly asks to suspend this specific cluster_id; do
    not suspend clusters to answer cost or billing questions.

    Two steps: call with confirm=false (default) to get a preview of the cluster (name,
    status, plan, CU size) and the impact, without changing anything. Show it to the user
    and call again with confirm=true only after they confirm.

    Args:
        cluster_id: ID of the cluster to suspend
        confirm: false (default) returns the preview only; true suspends the cluster
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result> with confirm=false:
        {"confirm_required": true, "action": "suspend_cluster", "cluster": {"cluster_id",
        "cluster_name", "status", "plan", "cu_size", "region_id"}, "impact": "..."}
        <result> with confirm=true:
        Example:
        {
            "cluster_id": "inxx-xxxxxxxxxxxxxxx",
            "prompt": "Successfully Submitted. The cluster will not incur any computing costs when suspended. You will only be billed for the storage costs during this time."
        }
        
    """
    try:
        # Log request
        logger.info(f"SUSPEND_CLUSTER: cluster_id={cluster_id}, confirm={confirm}")

        if confirm is not True:
            data = openapi_client.control_plane_api_request(f"/v2/clusters/{cluster_id}", method="GET").get('data', {})
            status = data.get('status', 'Unknown')
            if status in ('SUSPENDED', 'SUSPENDING'):
                return hints.ok({
                    'confirm_required': False,
                    'action': 'suspend_cluster',
                    'cluster': {'cluster_id': data.get('clusterId', cluster_id),
                                'cluster_name': data.get('clusterName', 'Unknown'), 'status': status},
                    'message': f"The cluster is already {status}; nothing to suspend and no confirmation needed.",
                }, [hints.step("describe_cluster", "check the cluster status", cluster_id=cluster_id)],
                    ["Nothing was changed."])
            preview = {
                'confirm_required': True,
                'action': 'suspend_cluster',
                'cluster': {
                    'cluster_id': data.get('clusterId', cluster_id),
                    'cluster_name': data.get('clusterName', 'Unknown'),
                    'status': status,
                    'plan': data.get('plan', 'Unknown'),
                    'cu_size': data.get('cuSize', 0),
                    'region_id': data.get('regionId', 'Unknown'),
                },
                'impact': SUSPEND_IMPACT,
            }
            # Deliberately no next_steps: an executable suggestion with confirm=true would let
            # an agent skip the user's confirmation.
            preview['how_to_confirm'] = ("Show this to the user. Only if they explicitly agree, call "
                                         "suspend_cluster again with the same cluster_id and confirm=true.")
            return hints.ok(preview, None, ["Nothing was changed."])

        # Build URI with cluster_id as path parameter
        uri = f"/v2/clusters/{cluster_id}/suspend"
        
        response = openapi_client.control_plane_api_request(uri, method="POST")
        
        # Extract and format the response data
        data = response.get('data', {})
        cluster_info = {
            'cluster_id': data.get('clusterId', cluster_id),
            'prompt': data.get('prompt', 'Cluster suspension request submitted')
        }
        
        # Log results
        logger.info(f"SUSPEND_CLUSTER RESULT: cluster_id={cluster_info['cluster_id']}")
        
        return hints.ok(cluster_info, *ns.cluster_state_change(cluster_info['cluster_id'], "SUSPENDED"))
        
    except Exception as e:
        logger.error(f"SUSPEND_CLUSTER ERROR: {str(e)}")
        raise hints.tool_error("suspend_cluster", e, {"cluster_id": cluster_id}) from e

@write_tool(destructive=False, idempotent=True)
async def resume_cluster(cluster_id: str) -> str:
    """
    Resume a suspended dedicated cluster in Zilliz Cloud. This restarts compute billing for
    the cluster; only call it when the user asks to resume this specific cluster_id. The
    cluster takes several minutes to reach RUNNING.

    Args:
        cluster_id: ID of the cluster to resume
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result>:
        Dict containing cluster resumption info
        Example:
        {
            "cluster_id": "inxx-xxxxxxxxxxxxxxx",
            "prompt": "successfully Submitted. Cluster is being resumed, which is expected to takes several minutes. You can access data about the creation progress and status of your cluster by DescribeCluster API. Once the cluster status is RUNNING, you may access your vector database using the SDK."
        }
        
    """
    try:
        # Log request
        logger.info(f"RESUME_CLUSTER: cluster_id={cluster_id}")
        
        # Build URI with cluster_id as path parameter
        uri = f"/v2/clusters/{cluster_id}/resume"
        
        response = openapi_client.control_plane_api_request(uri, method="POST")
        
        # Extract and format the response data
        data = response.get('data', {})
        cluster_info = {
            'cluster_id': data.get('clusterId', cluster_id),
            'prompt': data.get('prompt', 'Cluster resumption request submitted')
        }
        
        # Log results
        logger.info(f"RESUME_CLUSTER RESULT: cluster_id={cluster_info['cluster_id']}")
        
        return hints.ok(cluster_info, *ns.cluster_state_change(cluster_info['cluster_id'], "RUNNING"))
        
    except Exception as e:
        logger.error(f"RESUME_CLUSTER ERROR: {str(e)}")
        raise hints.tool_error("resume_cluster", e, {"cluster_id": cluster_id}) from e

@read_tool()
async def query_cluster_metrics(
    cluster_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    period: Optional[str] = None,
    granularity: str = "PT30S",
    metric_queries: List[Dict[str, str]] = []
) -> str:
    """
    Query the metrics of a specific cluster.

    Args:
        cluster_id: ID of the target cluster
        start: Start time, ISO 8601 UTC timestamp, e.g. "2024-06-30T16:00:00Z" (use together with end)
        end: End time, ISO 8601 UTC timestamp (use together with start)
        period: Lookback duration in ISO 8601 using D/H/M/S units, e.g. "PT1H", "P1D", "P7D", "P180D"
            (use instead of start/end). Week and month units such as "P2W" or "P6M" are rejected;
            write 6 months as "P180D".
        granularity: Bucket size in ISO 8601, minimum PT30S (e.g. PT30S, PT1M, PT5M, PT1H, P1D).
            Choose it with care: at coarse granularities (PT1H, P1D) windows that have values at
            PT30S are often reported as null, so short or bursty traffic can look like none.
            Keep results small enough to read: about 450 points over all requested series
            (window / granularity x number of metrics), e.g. PT30S for up to 3 hours of one
            metric, PT2M for about 15 hours. The API itself rejects requests with roughly 40,000
            buckets (unknown error), but results that large are too long for clients to read.
            For long-range questions, query the long window for the overall shape, then confirm
            activity with a short recent window at PT30S; the result's notes summarise each series
            (buckets with a value, first/last such timestamp, max).
        metric_queries: List of objects {"metricName": <name>, "stat": "AVG"}. 'stat' is optional
            and defaults to AVG. The API ignores stat for aggregation: each bucket holds the value of
            the named metric. Latency percentiles are chosen by the metric NAME (..._LATENCY_AVG vs
            ..._LATENCY_P99), not by stat. Valid stat: AVG for every metric; P99 is also accepted
            for *_LATENCY_P99. Anything else is rejected locally with the valid values.
            metricName must be one of:
              Resource: CU_COMPUTATION, CU_CAPACITY, STORAGE_USE (GB), CLUSTER_WRITE_CAPACITY,
                READ_VCU, WRITE_VCU (Serverless clusters only; Dedicated clusters reject them)
                CU_SIZE (cluster size in CUs), REPLICA_COUNT: accepted and observed to return
                values, but not in the published metric list. A change in CU_SIZE marks a scaling
                step; check it when failures or latency changed suddenly.
              Throughput (per second): REQ_INSERT_COUNT, REQ_BULK_INSERT_COUNT, REQ_UPSERT_COUNT,
                REQ_DELETE_COUNT, REQ_SEARCH_COUNT, REQ_QUERY_COUNT, VECTOR_REQ_INSERT_COUNT,
                VECTOR_REQ_BULK_INSERT_COUNT, VECTOR_REQ_UPSERT_COUNT, VECTOR_REQ_DELETE_COUNT,
                VECTOR_REQ_SEARCH_COUNT; SLOW_QUERY_COUNT (per minute)
              Latency (ms): REQ_{INSERT,UPSERT,DELETE,SEARCH,QUERY}_LATENCY_AVG and
                REQ_{INSERT,UPSERT,DELETE,SEARCH,QUERY}_LATENCY_P99 (e.g. REQ_SEARCH_LATENCY_P99)
              Failure rate (percent, per operation): REQ_FAIL_RATE_INSERT, REQ_FAIL_RATE_BULK_INSERT,
                REQ_FAIL_RATE_UPSERT, REQ_FAIL_RATE_DELETE, REQ_FAIL_RATE_SEARCH, REQ_FAIL_RATE_QUERY.
                There is no overall success/fail rate metric; success rate = 100 - fail rate.
                Requests rejected by rate limiting or write quotas may not be counted as failures
                (open-source Milvus rejects them before the request handler), so 0% does not prove
                nothing was rejected; check client-side errors. Each bucket averages its whole
                interval (30 s at best), so a few seconds of errors show as a lower rate spread over
                several buckets and can peak after the errors stopped; use client logs to time
                short incidents.
              Data: ENTITIES_COUNT, ENTITIES_LOADED, ENTITIES_INDEXED, COLLECTIONS_COUNT,
                UNLOADED_COLLECTIONS_COUNT, FLUSH_COUNT (per minute). ENTITIES_COUNT and
                ENTITIES_LOADED are summed over ALL collections in the cluster, not a
                per-collection row count; for one collection use describe_collection -> rowCount.
    Returns:
        JSON {"notes": [...], "next_steps": [{"tool", "args", "why"}], "data": <result>};
        next_steps/notes are present only when useful. On failure the error text is JSON
        {"error", "message", "field", "expected", "got", "fix", "next_steps"}.
        <result> is {"results": [...]}. Values are strings. 'values' lists only buckets that have
        a value (may be "0", meaning zero); 'buckets' is the number of buckets in the series. Null
        buckets are listed in 'null_runs' as {status, from, to, points} per run of consecutive
        nulls, with status:
          - "unknown_or_no_failures": fail-rate is null but requests were served in that bucket.
            Usually nothing failed, but the metric cannot confirm it; do not report it as 0%.
          - "no_requests": latency / fail-rate is null and the request count was 0 in that bucket.
          - "no_data": no point reported (e.g. cluster not running yet, or the operation was never
            used); this is NOT zero.
        Results containing nulls also carry 'null_points' and a 'null_note' explaining them. For
        latency / fail-rate metrics the tool fetches the matching REQ_<OP>_COUNT for the same window
        to tell these cases apart. If the result would exceed the response size budget, every
        series keeps only its most recent buckets; a note says how many and next_steps gives the
        re-query for the older part.
        Example (full envelope, hints omitted):
        {
            "data": {
                "results": [
                    {
                        "name": "REQ_FAIL_RATE_SEARCH",
                        "stat": "AVG",
                        "unit": "percent",
                        "buckets": 2,
                        "values": [
                            {"timestamp": "2024-06-30T16:10:00Z", "value": "0.50"}
                        ],
                        "null_points": 1,
                        "null_runs": [{"status": "unknown_or_no_failures", "from": "2024-06-30T16:05:00Z",
                                       "to": "2024-06-30T16:05:00Z", "points": 1}],
                        "null_note": "..."
                    }
                ]
            }
        }

    """
    try:
        # Log request
        logger.info(f"QUERY_CLUSTER_METRICS: cluster_id={cluster_id}, metrics_count={len(metric_queries)}")

        # Build URI with cluster_id as path parameter
        uri = f"/v2/clusters/{cluster_id}/metrics/query"

        # Validate metric names / stat locally so the model gets the valid values immediately
        queries = metrics_catalog.validate_metric_queries(metric_queries)
        body = {
            'granularity': granularity,
            'metricQueries': queries
        }

        # Add time parameters (either start/end or period)
        if start and end:
            body['start'] = start
            body['end'] = end
        elif period:
            if metrics_catalog.duration_seconds(period) is None:
                raise ValueError(
                    f"period '{period}' is not supported. Use an ISO 8601 duration with D/H/M/S units, "
                    "e.g. 'PT1H', 'P1D', 'P7D', 'P30D', 'P180D' (6 months = 'P180D'; W and month units "
                    "are rejected by the API).")
            body['period'] = period
        else:
            raise ValueError("Either provide both 'start' and 'end', or provide 'period' (e.g. \"PT1H\")")

        names = [q['name'] for q in queries]
        try:
            response = openapi_client.control_plane_api_request(uri, body_map=body, method="POST")
        except Exception as api_err:
            # Keep the original exception (with .code / .http_status) for classification,
            # and add metric-specific advice to the structured error when it applies.
            structured = hints.tool_error("query_cluster_metrics", api_err,
                                          {"cluster_id": cluster_id, "metric_queries": metric_queries})
            extra_fix = metrics_catalog.api_error_fix(names)
            # Only for a generic rejection; keep PERMISSION_DENIED / AUTH_FAILED / ... advice intact.
            if extra_fix and structured.payload.get("error") == "API_ERROR":
                structured = hints.StructuredToolError(
                    {**structured.payload, "field": "metric_queries", "fix": extra_fix})
            raise structured from api_err

        data = response.get('data', {})
        results = data.get('results', [])

        # Explain nulls: fetch paired request-count series for latency / fail-rate metrics
        counts = metrics_catalog.series_by_timestamp(results)
        extra = metrics_catalog.needed_count_metrics(results, counts)
        if extra:
            extra_body = {k: v for k, v in body.items() if k != 'metricQueries'}
            extra_body['metricQueries'] = [{'name': n, 'stat': 'AVG'} for n in extra]
            try:
                extra_resp = openapi_client.control_plane_api_request(uri, body_map=extra_body, method="POST")
                counts.update(metrics_catalog.series_by_timestamp(
                    extra_resp.get('data', {}).get('results', [])))
            except Exception as pair_err:
                logger.warning(f"QUERY_CLUSTER_METRICS: paired count lookup failed: {pair_err}")
        metrics_catalog.annotate(results, counts)

        logger.info(f"QUERY_CLUSTER_METRICS RESULT: returned {len(results)} metric results")

        steps, notes = ns.query_cluster_metrics(data, cluster_id)
        cov_steps, cov_notes = metrics_catalog.coverage_hints(
            results, cluster_id, metric_queries, granularity, period, start, end)
        summary = metrics_catalog.series_summary(results, granularity)
        caveat = metrics_catalog.fail_rate_caveat(results)
        # Hints above are computed on the full result; the output is compacted and, if still over
        # the shared response budget, trimmed to the most recent buckets. The budget covers the
        # whole output (notes + next_steps + data): shrink the results budget by any excess.
        budget = RESULT_BUDGET
        for _ in range(4):
            data['results'], trim = metrics_catalog.fit_results(results, budget)
            trim_steps, trim_notes = [], []
            if trim:
                st, tn = metrics_catalog.trim_hints(trim, cluster_id, metric_queries, granularity)
                trim_steps, trim_notes = ([st] if st else []), [tn]
            out = hints.ok(data, cov_steps + trim_steps + steps,
                           ([summary] if summary else []) + trim_notes + cov_notes
                           + ([caveat] if caveat else []) + notes)
            excess = len(out.encode()) - RESULT_BUDGET
            if excess <= 0:
                break
            budget -= excess + 100
        return out

    except Exception as e:
        logger.error(f"QUERY_CLUSTER_METRICS ERROR: {str(e)}")
        raise hints.tool_error("query_cluster_metrics", e,
                               {"cluster_id": cluster_id, "metric_queries": metric_queries}) from e




