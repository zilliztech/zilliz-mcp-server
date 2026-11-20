"""Unit tests for the result envelope, structured errors and next-step generators."""

import json

import pytest
import requests

from zilliz_mcp_server.common import hints
from zilliz_mcp_server.common import next_steps as ns
from zilliz_mcp_server.common.hints import ZillizAPIError, classify_error, tool_error

CID, REG = "in01-abc123", "gcp-us-west1"


class TestEnvelope:
    def test_ok_omits_empty_hint_keys(self):
        assert json.loads(hints.ok([1, 2])) == {"data": [1, 2]}

    def test_ok_caps_steps_and_notes(self):
        steps = [hints.step("t", "w", a=i) for i in range(10)]
        out = json.loads(hints.ok({}, steps, ["n"] * 10))
        assert len(out["next_steps"]) == hints.MAX_NEXT_STEPS
        assert len(out["notes"]) == hints.MAX_NOTES
        assert out["next_steps"][0] == {"tool": "t", "args": {"a": 0}, "why": "w"}

    def test_tool_error_str_is_json(self):
        err = tool_error("x", ValueError("region_id is required and cannot be empty"), {"cluster_id": CID})
        payload = json.loads(str(err))
        assert payload["error"] == "REGION_MISSING"
        assert payload["next_steps"][0]["tool"] == "describe_cluster"
        assert payload["next_steps"][0]["args"] == {"cluster_id": CID}


class TestClassifyError:
    # Messages below are verbatim server responses observed on Zilliz Cloud.
    def test_cluster_not_found(self):
        e = ZillizAPIError("Cluster not found. Please use the ListClusters API to obtain your scoped clusters.", code=96018)
        p = classify_error("describe_cluster", e, {"cluster_id": "my-cluster"})
        assert p["error"] == "CLUSTER_NOT_FOUND" and p["field"] == "cluster_id"
        assert "not the cluster name" in p["fix"]
        assert p["next_steps"][0]["tool"] == "list_clusters"

    def test_region_mismatch(self):
        p = classify_error("search", ValueError("region_id does not match the resolved cluster"),
                           {"cluster_id": CID, "region_id": "aws-us-east-1"})
        assert p["error"] == "REGION_MISMATCH" and p["got"] == "aws-us-east-1"

    def test_collection_not_found(self):
        e = ZillizAPIError("can't find collection[database=default][collection=nope]", code=100)
        p = classify_error("describe_collection", e,
                           {"cluster_id": CID, "region_id": REG, "collection_name": "nope"})
        assert p["error"] == "COLLECTION_NOT_FOUND" and p["got"] == "nope"
        assert [s["tool"] for s in p["next_steps"]] == ["list_collections", "list_databases"]

    def test_vector_field_not_found(self):
        e = ZillizAPIError("can only accept json format request, error: cannot find a vector field: "
                           "field not found[field=vec_nope]", code=1801)
        p = classify_error("search", e, {"cluster_id": CID, "region_id": REG,
                                         "collection_name": "c", "anns_field": "vec_nope"})
        assert p["error"] == "FIELD_NOT_FOUND" and p["field"] == "anns_field" and p["got"] == "vec_nope"
        assert p["next_steps"][0]["tool"] == "describe_collection"

    def test_filter_field_not_found(self):
        e = ZillizAPIError("failed to create query plan: cannot parse expression: nope_f > 1: "
                           "field nope_f not exist: invalid parameter", code=1100)
        p = classify_error("query", e, {"collection_name": "c", "filter": "nope_f > 1"})
        assert p["field"] == "filter" and p["got"] == "nope_f"

    def test_dimension_mismatch(self):
        e = ZillizAPIError("can only accept json format request, error: dimension: 1024, but length of "
                           "[]float: 8: invalid parameter[expected=FloatVector]", code=1801)
        p = classify_error("search", e, {"collection_name": "c"})
        assert p["error"] == "DIMENSION_MISMATCH"
        assert p["expected"] == "vectors of length 1024" and p["got"] == "vector of length 8"

    def test_long_message_truncated(self):
        e = ZillizAPIError("dimension: 1024, but length of []float: 768: actual=[[" + "0.1, " * 800 + "]]", code=1801)
        p = classify_error("search", e, {})
        assert p["error"] == "DIMENSION_MISMATCH"
        assert len(p["message"]) <= hints.MAX_MESSAGE_CHARS + len(" ...(truncated)... ")
        assert p["message"].endswith("]]")  # tail kept

    def test_401_with_denied_text_is_auth_failed(self):
        e = requests.exceptions.HTTPError("401")
        e.http_status, e.api_message = 401, "access denied"
        assert classify_error("x", e)["error"] == "AUTH_FAILED"

    def test_list_clusters_empty_does_not_suggest_create(self):
        steps, notes = ns.list_clusters([], page_size=10, current_page=1)
        assert steps == [] and notes

    @pytest.mark.parametrize("msg,code,status", [
        ("The apikey is illegal", 21119, 401),
        ("user hasn't authenticated", 1800, 401),
    ])
    def test_auth(self, msg, code, status):
        e = requests.exceptions.HTTPError("401 Client Error")
        e.code, e.api_message, e.http_status = code, msg, status
        p = classify_error("list_clusters", e)
        assert p["error"] == "AUTH_FAILED" and p["field"] == "ZILLIZ_CLOUD_TOKEN"

    def test_permission_denied(self):
        e = requests.exceptions.HTTPError("403")
        e.http_status = 403
        assert classify_error("x", e)["error"] == "PERMISSION_DENIED"

    def test_missing_acl_permission(self):
        # Verbatim shape of GET /v2/invoices with a key lacking billing access (HTTP 200, code 96041).
        e = ZillizAPIError("Missing ACL permission: orgId=org-xxxx, resource=billing, action=view", code=96041)
        p = classify_error("x", e)
        assert p["error"] == "PERMISSION_DENIED"
        assert p["got"] == "resource=billing, action=view"
        assert p["missing_permission"] == "billing:view"
        assert "Organization Owner" in p["who_can_grant"]
        assert "Members > Edit Role" in p["message_for_admin"] and "API Keys" in p["message_for_admin"] and "billing:view" in p["message_for_admin"]
        assert "Tell the user" in p["fix"]
        assert p["next_steps"][0]["tool"] == "x"

    def test_permission_denied_retry_keeps_args(self):
        e = ZillizAPIError("Missing ACL permission: orgId=o, resource=cluster, action=view", code=96041)
        p = classify_error("describe_cluster", e, {"cluster_id": CID})
        assert p["next_steps"][0] == {"tool": "describe_cluster", "args": {"cluster_id": CID},
                                      "why": p["next_steps"][0]["why"]}

    def test_permission_fix_names_the_exact_retry_call(self):
        e = ZillizAPIError("Missing ACL permission: orgId=o, resource=billing, action=view", code=96041)
        p = classify_error("list_invoices", e, {"start": "2025-03-01", "end": None})
        assert 'After access is granted, retry list_invoices(start="2025-03-01")' in p["fix"]
        p = classify_error("describe_cluster", e, {"cluster_id": CID})
        assert f'retry describe_cluster(cluster_id="{CID}")' in p["fix"]

    def test_unknown_keeps_message(self):
        p = classify_error("x", Exception("weird"))
        assert p["error"] == "INTERNAL_ERROR" and p["message"] == "weird"

    def test_local_value_error_not_truncated(self):
        msg = "Unknown metric name 'X'. Valid metric names: " + ", ".join(f"M{i}" for i in range(200))
        p = classify_error("query_cluster_metrics", ValueError(msg))
        assert p["error"] == "INVALID_ARGUMENT" and p["message"] == msg


class TestNextSteps:
    def test_list_collections_empty(self):
        steps, _ = ns.list_collections([], CID, REG, "")
        assert [s["tool"] for s in steps] == ["list_databases", "create_collection"]

    def test_list_collections_nonempty_uses_first(self):
        steps, _ = ns.list_collections(["a", "b"], CID, REG, "db1")
        assert steps[0]["tool"] == "describe_collection"
        assert steps[0]["args"] == {"cluster_id": CID, "region_id": REG, "db_name": "db1", "collection_name": "a"}

    def test_describe_cluster_suspended(self):
        steps, _ = ns.describe_cluster({"cluster_id": CID, "status": "SUSPENDED"})
        assert steps == [hints.step("resume_cluster", steps[0]["why"], cluster_id=CID)]

    def test_describe_cluster_running(self):
        steps, notes = ns.describe_cluster({"cluster_id": CID, "region_id": REG, "status": "RUNNING", "plan": "Free"})
        assert steps[0]["tool"] == "list_databases" and steps[0]["args"]["region_id"] == REG
        assert notes

    def test_describe_collection_builds_search_args(self):
        data = {
            "collectionName": "my_collection",
            "fields": [
                {"name": "id", "type": "Int64", "primaryKey": True},
                {"name": "text", "type": "VarChar"},
                {"name": "vector", "type": "FloatVector", "params": [{"key": "dim", "value": "1024"}]},
            ],
            "indexes": [{"fieldName": "vector", "metricType": "COSINE"}],
            "load": "LoadStateLoaded",
        }
        steps, notes = ns.describe_collection(data, CID, REG, "")
        search = steps[0]
        assert search["tool"] == "search"
        assert search["args"]["anns_field"] == "vector"
        assert search["args"]["data"] == ["<1024 floats>"]
        assert search["args"]["output_fields"] == ["text"]
        assert steps[1]["tool"] == "query" and steps[1]["args"]["filter"] == "id >= 0"
        assert "larger distance" in notes[0]

    def test_describe_collection_not_loaded(self):
        data = {"collectionName": "c", "fields": [], "load": "LoadStateNotLoad"}
        _, notes = ns.describe_collection(data, CID, REG, "")
        assert any("LoadStateNotLoad" in n for n in notes)

    def test_list_clusters_full_page_and_suspended(self):
        clusters = [{"cluster_id": "in01-a", "status": "SUSPENDED", "region_id": REG},
                    {"cluster_id": "in01-b", "status": "RUNNING", "region_id": REG, "cluster_name": "b"}]
        steps, notes = ns.list_clusters(clusters, page_size=2, current_page=1)
        assert steps[0]["args"]["current_page"] == 2
        assert steps[1]["args"] == {"cluster_id": "in01-b", "region_id": REG}
        assert "in01-a" in notes[0]

    def test_query_pagination(self):
        steps, _ = ns.query([{}] * 5, CID, REG, "", "c", "id > 0", 5, 0, None)
        assert steps[0]["args"]["offset"] == 5
        steps, notes = ns.query([], CID, REG, "", "c", "id > 0", 5, 0, None)
        assert not steps and notes

    def test_search_empty_with_filter(self):
        steps, notes = ns.search([], CID, REG, "", "c", "x > 1", None)
        assert not steps and len(notes) == 2

    def test_search_nonempty_quiet(self):
        assert ns.search([{"id": 1, "distance": 0.9, "text": "t"}], CID, REG, "", "c", "", ["text"]) == ([], [])

    def test_metrics_all_empty(self):
        _, notes = ns.query_cluster_metrics({"results": [{"name": "A", "values": []}]}, CID)
        assert "No data points" in notes[0]


def test_hints_precede_data_so_truncation_keeps_them():
    out = hints.ok({"results": ["x" * 1000]}, [hints.step("t", "w")], ["n"])
    assert out.index('"notes"') < out.index('"next_steps"') < out.index('"data"')
