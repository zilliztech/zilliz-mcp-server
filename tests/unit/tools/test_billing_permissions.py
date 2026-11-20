"""Permission / auth error handling, invoice docs and request timeouts for the billing tools."""

import json
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import HTTPError

from zilliz_mcp_server.common.hints import StructuredToolError, ZillizAPIError
from zilliz_mcp_server.tools.zilliz import billing_tools

ACL_ERROR = "Business error: Missing ACL permission: orgId=org-x, resource=billing, action=view"


def _call(tool, **kwargs):
    import asyncio
    return asyncio.run(getattr(billing_tools, tool)(**kwargs))


def _payload(exc):
    assert isinstance(exc, StructuredToolError)
    return exc.payload


TOOL_CALLS = [
    ("get_usage_summary", {"start": "2026-11-01", "end": "2026-11-03"}),
    ("query_daily_usage", {"start": "2026-11-01", "end": "2026-11-03"}),
    ("list_invoices", {}),
    ("describe_invoice", {"invoice_id": "inv-x"}),
]


class TestPermissionDenied:
    @pytest.mark.parametrize("tool,kwargs", TOOL_CALLS)
    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    def test_acl_business_error_becomes_structured_error(self, mock_client, tool, kwargs):
        mock_client.control_plane_api_request.side_effect = ZillizAPIError(ACL_ERROR, code=96041)
        with pytest.raises(Exception) as e:
            _call(tool, **kwargs)
        payload = _payload(e.value)
        assert payload["error"] == "PERMISSION_DENIED"
        assert payload["field"] == "ZILLIZ_CLOUD_TOKEN"
        assert "Missing ACL permission" in payload["message"]
        # 1. what is missing  2. who grants  3. where  4. what to retry  5. forwardable message
        assert payload["missing_permission"] == "billing:view"
        assert "Organization Owner" in payload["who_can_grant"]
        # Both key types: personal key -> user's role; customized key -> the key's own role.
        assert "Access Control > Members > Edit Role" in payload["fix"]
        assert "customized API key" in payload["fix"] and "API Keys" in payload["fix"]
        assert "Organization Billing Admin" in payload["required_role"]
        assert payload["next_steps"][0]["tool"] == tool
        assert kwargs.items() <= payload["next_steps"][0]["args"].items()
        assert "Organization Billing Admin" in payload["message_for_admin"]
        assert "billing:view" in payload["message_for_admin"]
        assert "customized API key" in payload["message_for_admin"]

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    def test_error_with_code_attribute(self, mock_client):
        mock_client.control_plane_api_request.side_effect = ZillizAPIError("billing view denied", code=96041)
        with pytest.raises(Exception) as e:
            _call("list_invoices")
        assert _payload(e.value)["error"] == "PERMISSION_DENIED"

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    def test_http_403_is_permission_denied(self, mock_client):
        err = HTTPError("403 Client Error", response=MagicMock(status_code=403))
        err.http_status = 403
        mock_client.control_plane_api_request.side_effect = err
        with pytest.raises(Exception) as e:
            _call("list_invoices")
        assert _payload(e.value)["error"] == "PERMISSION_DENIED"

    @pytest.mark.parametrize("http_status,code", [(401, 21119), (401, None), (200, 1800)])
    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    def test_invalid_key_is_auth_failed_not_permission(self, mock_client, http_status, code):
        # Observed: an invalid key on /v2/invoices -> HTTP 401 {"code":21119,"message":"The apikey is illegal"}.
        err = ZillizAPIError("The apikey is illegal", code=code, http_status=http_status)
        mock_client.control_plane_api_request.side_effect = err
        with pytest.raises(Exception) as e:
            _call("list_invoices")
        payload = _payload(e.value)
        assert payload["error"] == "AUTH_FAILED"
        assert "missing_permission" not in payload
        assert "Billing Admin" not in json.dumps(payload)

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    def test_96041_in_invoice_id_is_not_permission(self, mock_client):
        mock_client.control_plane_api_request.side_effect = ZillizAPIError(
            "Invoice inv-96041 not found", code=404)
        with pytest.raises(Exception) as e:
            _call("describe_invoice", invoice_id="inv-96041")
        assert _payload(e.value)["error"] != "PERMISSION_DENIED"

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    def test_other_errors_keep_original_message(self, mock_client):
        mock_client.control_plane_api_request.side_effect = Exception("Business error: Internal error")
        with pytest.raises(Exception, match="Business error: Internal error"):
            _call("list_invoices")

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    def test_long_server_message_is_truncated(self, mock_client):
        mock_client.control_plane_api_request.side_effect = ZillizAPIError(ACL_ERROR + " x" * 400, code=96041)
        with pytest.raises(Exception) as e:
            _call("list_invoices")
        msg = _payload(e.value)["message"]
        # Only the server's text is cut (head + tail); the five user-facing points stay whole.
        assert len(msg.split("(Server message: ", 1)[1]) <= 320
        assert "...(truncated)..." in msg
        assert "Then retry: list_invoices(" in msg and "Message to forward to the admin:" in msg


class TestInvoiceDocsAndAmounts:
    def test_status_enum_matches_public_docs(self):
        doc = billing_tools.list_invoices.__doc__
        assert "paid, void" in doc
        assert "free" not in doc

    def test_amount_unit_documented_as_whole_currency_units(self):
        # Measured against real invoices: usage_amount matched the summed daily usage (USD) within ~1%.
        doc = billing_tools.list_invoices.__doc__
        assert "whole units of currency" in doc and "not cents" in doc
        assert "does not say whether" not in doc

    def test_usage_docs_say_before_credits(self):
        assert "BEFORE credits" in billing_tools.get_usage_summary.__doc__
        assert "BEFORE credits" in billing_tools.query_daily_usage.__doc__

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    def test_list_invoices_passes_amounts_through_with_note(self, mock_client):
        # Shape follows the public List Invoices response example.
        mock_client.control_plane_api_request.return_value = {
            "code": 0,
            "data": {"count": 1, "currentPage": 1, "pageSize": 10, "invoices": [
                {"id": "inv-1", "orgId": "org-1", "currency": "USD", "status": "void",
                 "usageAmount": 883850, "creditsApplied": 0, "total": 883850, "amountDue": 0}]},
        }
        result = json.loads(_call("list_invoices"))["data"]
        assert result["invoices"][0]["usage_amount"] == 883850
        assert result["invoices"][0]["status"] == "void"
        assert "whole units" in result["amount_unit_note"]

    @patch('zilliz_mcp_server.tools.zilliz.billing_tools.openapi_client')
    def test_describe_invoice_has_note(self, mock_client):
        mock_client.control_plane_api_request.return_value = {
            "code": 0, "data": {"id": "inv-1", "status": "paid", "total": 10}}
        result = json.loads(_call("describe_invoice", invoice_id="inv-1"))["data"]
        assert result["total"] == 10
        assert "amount_unit_note" in result


class TestRequestTimeout:
    @pytest.mark.parametrize("method", ["get", "post", "delete"])
    def test_every_request_has_timeout(self, method):
        from zilliz_mcp_server.common import openapi_client
        response = MagicMock(content=b'{"code":0,"data":{}}')
        response.json.return_value = {"code": 0, "data": {}}
        with patch(f'zilliz_mcp_server.common.openapi_client.requests.{method}', return_value=response) as m:
            getattr(openapi_client, method)("https://api.example.com/v2/x")
        assert m.call_args.kwargs["timeout"] == openapi_client.REQUEST_TIMEOUT
