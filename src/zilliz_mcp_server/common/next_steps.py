"""Per-tool next-step generators.

Each function looks at what a tool just returned (plus the arguments it was
called with) and returns ``(next_steps, notes)``. They return nothing when there
is nothing useful to say, so routine results stay short.
"""

from typing import Any, Dict, List, Optional, Tuple

from zilliz_mcp_server.common.hints import step

Hints = Tuple[List[Dict[str, Any]], List[str]]

_TRANSITIONAL = {"CREATING", "RESUMING", "SUSPENDING", "MODIFYING", "UPGRADING"}


def _dp(cluster_id: str, region_id: str, db_name: str = "") -> Dict[str, Any]:
    args = {"cluster_id": cluster_id, "region_id": region_id}
    if db_name:
        args["db_name"] = db_name
    return args


def _is_vector_type(t: str) -> bool:
    return t.endswith("Vector")


def _field_dim(field: Dict[str, Any]) -> Optional[int]:
    for p in field.get("params") or []:
        if p.get("key") == "dim":
            try:
                return int(p.get("value"))
            except (TypeError, ValueError):
                return None
    return None


# --- control plane ------------------------------------------------------------

def list_projects(projects: List[Dict[str, Any]]) -> Hints:
    if not projects:
        return [], ["This API key sees no projects; check that the key belongs to the right organization."]
    return [step("list_clusters", "List clusters across these projects.", page_size=100)], []


def list_clusters(clusters: List[Dict[str, Any]], page_size: int, current_page: int) -> Hints:
    steps: List[Dict[str, Any]] = []
    notes: List[str] = []
    if not clusters:
        if current_page > 1:
            return [], ["No clusters on this page; earlier pages hold all results."]
        return [], ["No clusters visible to this API key. If the user expects clusters, the key may belong to "
                    "another organization or project; do not create a cluster unless the user asks."]
    if len(clusters) >= page_size:
        steps.append(step("list_clusters", "This page is full; there may be more clusters.",
                          page_size=page_size, current_page=current_page + 1))
    suspended = [c for c in clusters if c.get("status") == "SUSPENDED"]
    running = [c for c in clusters if c.get("status") == "RUNNING"]
    if running:
        c = running[0]
        steps.append(step("list_databases", f"Explore data in cluster '{c.get('cluster_name')}'.",
                          cluster_id=c.get("cluster_id"), region_id=c.get("region_id")))
    if suspended:
        notes.append("SUSPENDED clusters reject data operations until resumed: "
                     + ", ".join(c.get("cluster_id", "") for c in suspended[:5]))
    notes.append("Data-plane tools need both cluster_id and region_id from this list.")
    return steps, notes


def create_free_cluster(info: Dict[str, Any]) -> Hints:
    return [step("describe_cluster", "Poll until status is RUNNING before using data-plane tools.",
                 cluster_id=info.get("cluster_id"))], []


def describe_cluster(info: Dict[str, Any]) -> Hints:
    status = info.get("status")
    cid = info.get("cluster_id")
    if status == "SUSPENDED":
        return [step("resume_cluster", "Cluster is SUSPENDED; data operations fail until it is resumed.",
                     cluster_id=cid)], []
    if status in _TRANSITIONAL:
        return [step("describe_cluster", f"Cluster is {status}; poll again in a minute until RUNNING.",
                     cluster_id=cid)], []
    if status == "RUNNING":
        notes = []
        if info.get("plan") in ("Free", "Serverless"):
            notes.append("Free/Serverless cluster: leave db_name empty in data-plane tools.")
        return [step("list_databases", "List databases in this cluster.",
                     cluster_id=cid, region_id=info.get("region_id"))], notes
    return [], []


def cluster_state_change(cluster_id: str, target: str) -> Hints:
    return [step("describe_cluster", f"Poll until status is {target}; the change takes several minutes.",
                 cluster_id=cluster_id)], []


def query_cluster_metrics(data: Dict[str, Any], cluster_id: str) -> Hints:
    results = (data or {}).get("results") or []
    empty = [r.get("name") for r in results if not r.get("values")]
    if results and len(empty) == len(results):
        return [], ["No data points in this window for any metric; try a longer period (e.g. 'P1D') "
                    "or check that the cluster is RUNNING."]
    if empty:
        return [], ["No data points for: " + ", ".join(str(n) for n in empty[:10])]
    return [], []


# --- data plane -----------------------------------------------------------------

def list_databases(databases: List[str], cluster_id: str, region_id: str) -> Hints:
    if not databases:
        return [step("list_collections", "Free/Serverless clusters have no database list; "
                     "list collections with db_name empty.", **_dp(cluster_id, region_id))], []
    db = "default" if "default" in databases else databases[0]
    notes = []
    if len(databases) > 1:
        notes.append("Collections are scoped per database; pass db_name to collection tools.")
    return [step("list_collections", f"List collections in database '{db}'.",
                 **_dp(cluster_id, region_id, "" if db == "default" else db))], notes


def list_collections(collections: List[str], cluster_id: str, region_id: str, db_name: str) -> Hints:
    if not collections:
        return [step("list_databases", "This database is empty; collections may be in another database.",
                     cluster_id=cluster_id, region_id=region_id),
                step("create_collection", "Or create one here.", **_dp(cluster_id, region_id, db_name),
                     collection_name="<name>", dimension="<embedding dim>")], []
    return [step("describe_collection", "Read the schema (vector field, dim, scalar fields) before search/query.",
                 **_dp(cluster_id, region_id, db_name), collection_name=collections[0])], []


def create_collection(cluster_id: str, region_id: str, db_name: str, collection_name: str,
                      dimension: int, auto_id: bool, primary_field_name: str, vector_field_name: str) -> Hints:
    row: Dict[str, Any] = {vector_field_name: f"<{dimension} floats>"}
    if not auto_id:
        row = {primary_field_name: "<id>", **row}
    return [step("insert_entities", "Insert rows; keys must match the schema.",
                 **_dp(cluster_id, region_id, db_name), collection_name=collection_name, data=[row])], []


def describe_collection(data: Dict[str, Any], cluster_id: str, region_id: str, db_name: str) -> Hints:
    fields = data.get("fields") or []
    name = data.get("collectionName")
    vectors = [f for f in fields if _is_vector_type(str(f.get("type", "")))]
    pk = next((f for f in fields if f.get("primaryKey")), None)
    scalars = [f.get("name") for f in fields if not _is_vector_type(str(f.get("type", ""))) and not f.get("primaryKey")]
    metrics = {i.get("fieldName"): i.get("metricType") for i in data.get("indexes") or []}
    steps: List[Dict[str, Any]] = []
    notes: List[str] = []
    base = _dp(cluster_id, region_id, db_name)
    if vectors:
        v = vectors[0]
        dim = _field_dim(v)
        args: Dict[str, Any] = {**base, "collection_name": name, "anns_field": v.get("name"),
                                "data": [f"<{dim} floats>" if dim else "<vector>"], "limit": 10}
        if scalars:
            args["output_fields"] = scalars[:5]
        steps.append(step("search", "Vector search; query vectors must come from the same embedding model.", **args))
        metric = metrics.get(v.get("name"))
        if metric:
            notes.append(f"'{v.get('name')}' uses {metric}: "
                         + ("smaller distance = more similar." if metric == "L2" else "larger distance = more similar."))
    if len(vectors) > 1:
        steps.append(step("hybrid_search", "Collection has several vector fields: "
                          + ", ".join(f.get("name") for f in vectors), **base, collection_name=name,
                          search_requests=[{"annsField": f.get("name"), "data": ["<vector>"], "limit": 10}
                                           for f in vectors[:2]],
                          rerank_strategy="rrf", rerank_params={"k": 60}, limit=10))
    if pk:
        pk_filter = f'{pk.get("name")} >= 0' if pk.get("type") == "Int64" else f'{pk.get("name")} != ""'
        steps.append(step("query", "Scalar filter / fetch rows without a vector.", **base, collection_name=name,
                          filter=pk_filter, output_fields=[f.get("name") for f in fields
                                                           if not _is_vector_type(str(f.get("type", "")))][:5],
                          limit=5))
    load = data.get("load")
    if load and load != "LoadStateLoaded":
        notes.append(f"Load state is {load}; search/query fail until the collection is loaded.")
    return steps, notes


def insert_entities(resp_data: Dict[str, Any], requested: int) -> Hints:
    count = (resp_data or {}).get("insertCount")
    if count is not None and count != requested:
        return [], [f"Requested {requested} rows but {count} were inserted."]
    return [], []


def delete_entities(cluster_id: str, region_id: str, db_name: str, collection_name: str, filter: str) -> Hints:
    if not filter:
        return [], []
    return [step("query", "Verify the rows are gone (expect an empty result).",
                 **_dp(cluster_id, region_id, db_name), collection_name=collection_name,
                 filter=filter, limit=1)], []


def search(results: List[Any], cluster_id: str, region_id: str, db_name: str, collection_name: str,
           filter: str, output_fields: Optional[List[str]]) -> Hints:
    if not results:
        notes = ["No hits."]
        steps = []
        if filter:
            notes.append("The filter may exclude everything; retry without it to confirm.")
        else:
            steps.append(step("describe_collection", "Check the collection has data loaded and the right vector field.",
                              **_dp(cluster_id, region_id, db_name), collection_name=collection_name))
        return steps, notes
    first = results[0] if isinstance(results[0], dict) else {}
    if not output_fields and set(first.keys()) <= {"id", "distance"}:
        return [step("describe_collection", "Hits only contain id/distance; pick scalar fields for output_fields.",
                     **_dp(cluster_id, region_id, db_name), collection_name=collection_name)], []
    return [], []


def query(results: List[Any], cluster_id: str, region_id: str, db_name: str, collection_name: str,
          filter: str, limit: int, offset: int, output_fields: Optional[List[str]]) -> Hints:
    if not results:
        return [], ["No rows match the filter."]
    if len(results) >= limit:
        args = {**_dp(cluster_id, region_id, db_name), "collection_name": collection_name, "filter": filter,
                "limit": limit, "offset": offset + limit}
        if output_fields:
            args["output_fields"] = output_fields
        return [step("query", "Result hit the limit; fetch the next page.", **args)], []
    return [], []


def hybrid_search(results: List[Any]) -> Hints:
    if not results:
        return [], ["No hits; check each search request's annsField, vector length and filter."]
    return [], []
