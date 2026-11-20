"""PERMISSION_DENIED: the five things the user needs come first and survive relaying."""

import json

from zilliz_mcp_server.common import hints
from zilliz_mcp_server.common.hints import classify_error, tool_error

# The API error class of common/hints.py (the one carrying code / http_status).
APIError = next(c for c in vars(hints).values()
                if isinstance(c, type) and issubclass(c, Exception) and c.__module__ == hints.__name__
                and c is not hints.StructuredToolError)

ACL = "Missing ACL permission: orgId=o, resource=billing, action=view"


def perm(tool="list_invoices", ctx=None, msg=ACL):
    return classify_error(tool, APIError(msg, code=96041), ctx if ctx is not None else {"start": "2025-03-01"})


def test_key_order_admin_message_and_retry_first():
    p = perm()
    assert list(p)[:4] == ["error", "message_for_admin", "retry_after_grant", "message"]
    assert p["retry_after_grant"] == 'list_invoices(start="2025-03-01")'


def test_message_carries_all_five_points_in_order():
    p = perm()
    m = p["message"]
    parts = ["Reply to the user with all five points below, and include the admin message verbatim",
             "1) The API key lacks the 'billing:view' permission.",
             "2) Who can grant it: an Organization Owner",
             "3) Where: Zilliz Cloud console; for a personal API key, Access Control > Members > Edit Role",
             '4) Then retry: list_invoices(start="2025-03-01") (tell the user: once the permission is '
             'granted, ask me to run list_invoices again).',
             '5) Message to forward to the admin: "' + p["message_for_admin"] + '"']
    pos = [m.index(x) for x in parts]
    assert pos == sorted(pos) and pos[0] == 0
    assert m.endswith("(Server message: " + ACL + ")")


def test_long_server_message_cut_but_five_points_kept():
    long_msg = ACL + " " + "x" * 1000
    p = perm(msg=long_msg)
    m = p["message"]
    assert "...(truncated)..." in m
    assert len(m.split("(Server message: ", 1)[1]) < 340
    assert 'Then retry: list_invoices(start="2025-03-01")' in m
    assert p["message_for_admin"] in m


def test_without_acl_detail_still_names_tool():
    p = classify_error("describe_cluster", APIError("permission denied", http_status=403), {"cluster_id": "in01-x"})
    assert "1) The API key lacks the permission needed for describe_cluster." in p["message"]
    assert p["retry_after_grant"] == 'describe_cluster(cluster_id="in01-x")'
    assert "missing_permission" not in p


def test_billing_tool_without_acl_detail_falls_back_to_billing_grant():
    p = classify_error("list_invoices", APIError("permission denied", http_status=403), {})
    assert p["who_can_grant"] == "an Organization Owner of the Zilliz Cloud organization"
    assert p["required_role"].startswith("the Organization Billing Admin role")
    assert "Project Admin" not in p["message"] and "Project Admin" not in p["fix"]
    assert "Billing Admin" in p["message_for_admin"]
    assert "1) The API key lacks the permission needed for list_invoices." in p["message"]
    assert "missing_permission" not in p
    q = classify_error("describe_cluster", APIError("permission denied", http_status=403), {})
    assert "Project Admin" in q["who_can_grant"]


def test_tool_error_text_starts_with_relayable_fields():
    text = str(tool_error("list_invoices", APIError(ACL, code=96041), {"start": "2025-03-01"}))
    keys = list(json.loads(text))
    assert keys[1:3] == ["message_for_admin", "retry_after_grant"]
