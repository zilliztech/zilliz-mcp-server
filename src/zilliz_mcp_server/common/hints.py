"""Result envelope and structured error protocol shared by all tools.

Every tool returns a JSON text payload (MCP text content) with this shape::

    {
      "notes": ["..."],                    # optional, short caveats (first: survives truncation)
      "next_steps": [                      # optional, only when informative
        {"tool": "search", "args": {...}, "why": "..."}
      ],
      "data": <the tool's actual result>
    }

``next_steps`` entries are directly executable: ``tool`` is a tool name exposed by
this server and ``args`` is the argument object for the next call. Values that the
server cannot know (for example a query vector) are given as ``"<placeholder>"``
strings describing the expected shape.

Errors are raised as :class:`StructuredToolError`; its message is a JSON object::

    {
      "error": "COLLECTION_NOT_FOUND",
      "message": "<original server message>",
      "field": "collection_name",
      "expected": "...",
      "got": "...",
      "fix": "<one sentence on how to correct the call>",
      "next_steps": [...]
    }

Keys whose value is unknown are omitted. MCP clients receive it as a text
content block with ``isError: true``.
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import requests

MAX_NEXT_STEPS = 3
MAX_NOTES = 3
MAX_MESSAGE_CHARS = 300


def step(tool: str, why: str, **args: Any) -> Dict[str, Any]:
    """Build one executable next-step suggestion."""
    return {"tool": tool, "args": args, "why": why}


def ok(data: Any, next_steps: Optional[List[Dict[str, Any]]] = None,
       notes: Optional[List[str]] = None) -> str:
    """Serialize a successful tool result in the envelope format.

    notes and next_steps come BEFORE data: MCP clients often truncate long tool output, and
    large results (e.g. metric series) would otherwise cut the hints off.
    """
    payload: Dict[str, Any] = {}
    kept_notes = [n for n in (notes or []) if n][:MAX_NOTES]
    if kept_notes:
        payload["notes"] = kept_notes
    steps = [s for s in (next_steps or []) if s][:MAX_NEXT_STEPS]
    if steps:
        payload["next_steps"] = steps
    payload["data"] = data
    return json.dumps(payload)


class ZillizAPIError(Exception):
    """Error returned by the Zilliz Cloud API (HTTP error or non-zero code)."""

    def __init__(self, message: str, code: Optional[int] = None,
                 http_status: Optional[int] = None):
        self.code = code
        self.http_status = http_status
        self.api_message = message
        prefix = f"Business error: {message}" if code is not None else message
        super().__init__(prefix)


class StructuredToolError(Exception):
    """Exception whose string form is the structured JSON error payload."""

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload
        super().__init__(json.dumps(payload))


def _clean(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


_DIM_RE = re.compile(r"dimension:\s*(\d+),\s*but length of \[\]float:\s*(\d+)")
_FIELD_RE = re.compile(r"field not found\[field=([^\]]+)\]|field (\S+) not exist")
_CLUSTER_ID_RE = re.compile(r"^in\d+-[0-9a-z]+$")
_ACL_RE = re.compile(r"resource=([\w-]+),\s*action=([\w-]+)")

# API error code for "Missing ACL permission" (HTTP 200, body code 96041).
_CODE_MISSING_ACL = 96041
# Tools that read organization billing data. When the error carries no resource/action, who can
# grant access is still known from the tool: billing is granted at organization level.
_BILLING_TOOL_RE = re.compile(r"billing|invoice|usage")


_WHERE_TO_GRANT = (
    "If it is a personal API key, it inherits the user's organization role: change the user's role under "
    "Access Control > Members > Edit Role. If it is a customized API key, edit the key's role under API Keys.")


def _call_repr(tool: str, ctx: Optional[Dict[str, Any]]) -> str:
    """tool(arg=value, ...) for the retry instruction; long values are shortened."""
    parts = []
    for k, v in (ctx or {}).items():
        if v in (None, "", [], {}):
            continue
        text = json.dumps(v, default=str)
        parts.append(f"{k}={text if len(text) <= 60 else text[:57] + '...'}")
    return f"{tool}({', '.join(parts)})"


def _permission_fix(resource: Optional[str], action: Optional[str], tool: str = "the tool",
                    ctx: Optional[Dict[str, Any]] = None) -> str:
    what = f"'{action}' on '{resource}'" if resource and action else "this operation"
    return (f"The API key is valid but is not allowed to perform {what}. Tell the user: {_who_grants(resource)} "
            f"must grant {_role_needed(resource, action)} in the Zilliz Cloud console. {_WHERE_TO_GRANT} "
            f"Alternatively configure the MCP server with a key that already has it. Retrying with other "
            f"arguments will not help. After access is granted, retry {_call_repr(tool, ctx)} with the same "
            f"arguments.")


def _who_grants(resource: Optional[str]) -> str:
    if resource == "billing":
        return "an Organization Owner of the Zilliz Cloud organization"
    return "an Organization Owner (or a Project Admin of the cluster's project)"


def _role_needed(resource: Optional[str], action: Optional[str]) -> str:
    if resource == "billing":
        return "the Organization Billing Admin role (or Organization Owner)"
    if resource:
        return f"a role that grants '{action or 'access'}' on '{resource}'"
    return "a role that allows this operation"


def _admin_message(tool: str, resource: Optional[str], action: Optional[str]) -> str:
    perm = f"'{resource}:{action}'" if resource and action else f"the permission needed for '{tool}'"
    return (f"Hi, could you grant {_role_needed(resource, action)} to the Zilliz Cloud API key we use? It "
            f"currently lacks {perm}. In the Zilliz Cloud console: for a personal API key, go to Access Control > "
            f"Members > Edit Role for my user; for a customized API key, edit that key's role under API Keys. "
            f"Thanks!")


def _permission_message(tool: str, resource: Optional[str], action: Optional[str], retry: str,
                        admin_msg: str, server_msg: str) -> str:
    """User-facing message for PERMISSION_DENIED: the five things the user needs, in the order they
    act on them, so a model relaying only 'message' still passes all of them on. The server's own
    text comes last and is the only part subject to the length rule. The first sentence tells the
    agent to relay all five points and the admin message verbatim, which models otherwise paraphrase
    or drop."""
    missing = f"the '{resource}:{action}' permission" if resource and action else f"the permission needed for {tool}"
    return (f"{_RELAY_INSTRUCTION} 1) The API key lacks {missing}. 2) Who can grant it: {_who_grants(resource)}, "
            f"by giving the key {_role_needed(resource, action)}. 3) Where: Zilliz Cloud console; for a personal "
            f"API key, Access Control > Members > Edit Role; for a customized API key, the key's role under API "
            f"Keys. 4) Then retry: {retry} (tell the user: once the permission is granted, ask me to run {tool} "
            f"again). 5) Message to forward to the admin: \"{admin_msg}\" (Server message: {server_msg})")


_RELAY_INSTRUCTION = ("Reply to the user with all five points below, and include the admin message verbatim "
                      "(translate it if the user writes in another language).")


def classify_error(tool: str, exc: Exception, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Map an exception raised while running ``tool`` to the structured error payload.

    ``ctx`` holds the arguments the tool was called with (cluster_id, region_id,
    collection_name, db_name, anns_field, ...). It is used to fill ``got`` and to
    build next steps with the caller's own values.
    """
    ctx = ctx or {}
    if isinstance(exc, StructuredToolError):
        return exc.payload

    message = getattr(exc, "api_message", None) or str(exc)
    low = message.lower()
    code = getattr(exc, "code", None)
    http_status = getattr(exc, "http_status", None)
    cluster_id = ctx.get("cluster_id")
    region_id = ctx.get("region_id")
    db_name = ctx.get("db_name") or ""
    collection = ctx.get("collection_name")
    dp_args = _clean({"cluster_id": cluster_id, "region_id": region_id})

    # Server messages can echo the whole request (e.g. every float of a query vector).
    # Keep head + tail: the actual cause can follow the echoed payload.
    # Local validation messages (ValueError) are ours and may list valid choices: never cut them.
    short = message if (len(message) <= MAX_MESSAGE_CHARS or isinstance(exc, ValueError)) else (
        message[:200] + " ...(truncated)... " + message[-100:])

    def build(kind: str, **kw: Any) -> Dict[str, Any]:
        return _clean({"error": kind, "message": short, **kw})

    # --- authentication / authorization -------------------------------------
    is_401 = http_status == 401 or code in (21119, 1800)
    if not is_401 and (http_status == 403 or code == _CODE_MISSING_ACL or "missing acl permission" in low
                       or "permission denied" in low):
        acl = _ACL_RE.search(message)
        resource, action = (acl.group(1), acl.group(2)) if acl else (None, None)
        grant = resource or ("billing" if _BILLING_TOOL_RE.search(tool) else None)
        retry = _call_repr(tool, ctx)
        admin_msg = _admin_message(tool, grant, action)
        # Key order matters: clients truncate and models relay the first keys. The message for the
        # admin and the retry call come right after 'error'; 'message' repeats all five points.
        return _clean(dict(
            error="PERMISSION_DENIED",
            message_for_admin=admin_msg,
            retry_after_grant=retry,
            message=_permission_message(tool, grant, action, retry, admin_msg, short),
            missing_permission=f"{resource}:{action}" if acl else None,
            who_can_grant=_who_grants(grant),
            required_role=_role_needed(grant, action),
            field="ZILLIZ_CLOUD_TOKEN",
            expected=f"an API key whose role allows '{action}' on '{resource}'" if acl
            else "an API key whose role allows this operation",
            got=f"resource={resource}, action={action}" if acl else None,
            fix=_permission_fix(grant, action, tool, ctx),
            next_steps=[step(tool, "Retry your previous call unchanged once the permission is granted "
                                   "(args lists only the identifying arguments).",
                             **_clean(ctx))],
        ))
    if (http_status == 401 or code in (21119, 1800)
            or "apikey is illegal" in low or "authenticated" in low
            or "unauthorized" in low):
        return build(
            "AUTH_FAILED",
            field="ZILLIZ_CLOUD_TOKEN",
            expected="a valid, unrevoked Zilliz Cloud API key",
            fix="The API key was rejected (invalid, expired or revoked). Tell the user to set a valid key in the "
                "ZILLIZ_CLOUD_TOKEN environment variable of the MCP server. Retrying with other arguments will not help.",
        )

    # --- argument validation done locally -----------------------------------
    if "region_id is required" in low:
        return build(
            "REGION_MISSING", field="region_id", expected="a region id such as 'aws-us-west-2' or 'gcp-us-west1'",
            got=region_id or "",
            fix="Pass region_id. Read it from the 'region_id' field of describe_cluster or list_clusters.",
            next_steps=[step("describe_cluster", "Its 'region_id' field is the value to pass.", cluster_id=cluster_id)]
            if cluster_id else [step("list_clusters", "Find the cluster and its region_id.", page_size=100)],
        )
    if "region_id does not match" in low:
        return build(
            "REGION_MISMATCH", field="region_id", got=region_id,
            expected="the region_id reported by describe_cluster for this cluster",
            fix="Use the 'region_id' returned by describe_cluster for this cluster_id.",
            next_steps=[step("describe_cluster", "Read the correct region_id.", cluster_id=cluster_id)],
        )
    if "cluster_id is required" in low:
        return build(
            "CLUSTER_ID_MISSING", field="cluster_id", expected="a cluster id like 'in01-xxxxxxxxxxxxxxx'",
            fix="Pass cluster_id. Get it from list_clusters.",
            next_steps=[step("list_clusters", "Find the cluster_id.", page_size=100)],
        )
    if "either provide both 'start' and 'end', or provide 'period'" in low:
        return build(
            "INVALID_ARGUMENT", field="period", expected="period like 'PT1H' or 'P1D', or both start and end (ISO 8601)",
            fix="Pass period (e.g. 'PT1H'), or both start and end.",
        )
    if "metricname" in low and "stat" in low and "must contain" in low:
        return build(
            "INVALID_ARGUMENT", field="metric_queries",
            expected='[{"metricName": "<METRIC_NAME>", "stat": "AVG"}]',
            got=ctx.get("metric_queries"),
            fix="Each metric query needs both 'metricName' and 'stat'.",
        )

    # --- control plane --------------------------------------------------------
    if code == 96018 or "cluster not found" in low:
        got = cluster_id
        fix = "Use a cluster_id returned by list_clusters."
        if cluster_id and not _CLUSTER_ID_RE.match(cluster_id):
            fix = ("cluster_id must be the id (like 'in01-xxxxxxxxxxxxxxx'), not the cluster name. "
                   "Use the 'cluster_id' field from list_clusters.")
        return build(
            "CLUSTER_NOT_FOUND", field="cluster_id", got=got,
            expected="a cluster id visible to this API key, like 'in01-xxxxxxxxxxxxxxx'", fix=fix,
            next_steps=[step("list_clusters", "List clusters this API key can access.", page_size=100)],
        )

    # --- data plane -----------------------------------------------------------
    m = _DIM_RE.search(message)
    if m:
        expected_dim, got_dim = int(m.group(1)), int(m.group(2))
        return build(
            "DIMENSION_MISMATCH", field="data", expected=f"vectors of length {expected_dim}",
            got=f"vector of length {got_dim}",
            fix=f"Every query vector must have exactly {expected_dim} floats, produced by the same embedding "
                f"model used to build the collection.",
            next_steps=[step("describe_collection", "Confirm the vector field and its dim.",
                             **dp_args, collection_name=collection, **_clean({"db_name": db_name}))]
            if collection else [],
        )
    if "can't find collection" in low or "collection not found" in low:
        return build(
            "COLLECTION_NOT_FOUND", field="collection_name", got=collection,
            expected="an existing collection name in database " + (repr(db_name) if db_name else "'default'"),
            fix="Collection names are case-sensitive and scoped to a database. List collections, "
                "or pass db_name if it lives in another database.",
            next_steps=[step("list_collections", "See which collections exist in this database.",
                             **dp_args, **_clean({"db_name": db_name})),
                        step("list_databases", "The collection may be in another database.", **dp_args)],
        )
    if "database not found" in low or ("database" in low and "not exist" in low):
        return build(
            "DATABASE_NOT_FOUND", field="db_name", got=db_name,
            fix="Use a database name returned by list_databases.",
            next_steps=[step("list_databases", "List databases in this cluster.", **dp_args)],
        )
    m = _FIELD_RE.search(message)
    if m:
        bad = m.group(1) or m.group(2)
        field = "anns_field" if bad == ctx.get("anns_field") else (
            "filter" if ctx.get("filter") and bad in str(ctx.get("filter")) else "output_fields")
        return build(
            "FIELD_NOT_FOUND", field=field, got=bad,
            expected="a field name from the collection schema",
            fix="Field names come from describe_collection: use a vector field for anns_field and "
                "scalar fields in filter/output_fields.",
            next_steps=[step("describe_collection", "Read the real field names and types.",
                             **dp_args, collection_name=collection, **_clean({"db_name": db_name}))]
            if collection else [],
        )
    if "not loaded" in low:
        return build(
            "COLLECTION_NOT_LOADED", field="collection_name", got=collection,
            fix="The collection must be loaded before search/query. Load it from the Zilliz Cloud console or SDK.",
        )

    # --- transport ------------------------------------------------------------
    if isinstance(exc, (requests.exceptions.Timeout, TimeoutError, asyncio.TimeoutError)):
        return build(
            "NETWORK_ERROR",
            fix="The request timed out before the API answered. Retry once; if it times out again, narrow the "
                "request (shorter time window, fewer days or fewer items).",
            next_steps=[step(tool, "Retry the same call; narrow the window if it times out again.", **_clean(ctx))],
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        return build(
            "NETWORK_ERROR",
            fix="Could not reach the endpoint. Check that the cluster is RUNNING and reachable from this host.",
            next_steps=[step("describe_cluster", "Check cluster status.", cluster_id=cluster_id)] if cluster_id else [],
        )

    if isinstance(exc, ValueError):
        return build("INVALID_ARGUMENT", fix="Read 'message'; it names the argument and the accepted values.")
    return build("API_ERROR" if code is not None or http_status else "INTERNAL_ERROR",
                 fix="Read 'message'; correct the argument it names and retry.")


def tool_error(tool: str, exc: Exception, ctx: Optional[Dict[str, Any]] = None) -> StructuredToolError:
    """Build the exception a tool should raise for ``exc``."""
    payload = classify_error(tool, exc, ctx)
    if "next_steps" in payload:
        payload["next_steps"] = payload["next_steps"][:MAX_NEXT_STEPS]
    return StructuredToolError(payload)
