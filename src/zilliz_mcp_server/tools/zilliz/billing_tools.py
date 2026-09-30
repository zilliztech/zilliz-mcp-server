"""Zilliz Control Plane billing tools."""

import json
import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional
from zilliz_mcp_server.common import openapi_client
from zilliz_mcp_server.app import zilliz_mcp

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# The usage API returns the whole range in one response (~70 KB per day for a
# busy org), so cap how much we pull through the server and into the agent.
MAX_SUMMARY_DAYS = 366
MAX_RAW_DAYS = 7

UNATTRIBUTED = "unattributed"

_GROUP_KEYS = {
    'cluster': lambda bucket, item: item.get('properties', {}).get('clusterId'),
    'project': lambda bucket, item: item.get('properties', {}).get('projectId'),
    'region': lambda bucket, item: item.get('properties', {}).get('regionId'),
    'cost_type': lambda bucket, item: item.get('costType'),
    'day': lambda bucket, item: bucket.get('intervalStart', '')[:10],
}

_INVOICE_FIELDS = {
    'invoice_id': 'id',
    'org_id': 'orgId',
    'period_start': 'periodStart',
    'period_end': 'periodEnd',
    'invoice_date': 'invoiceDate',
    'due_date': 'dueDate',
    'currency': 'currency',
    'status': 'status',
    'usage_amount': 'usageAmount',
    'credits_applied': 'creditsApplied',
    'already_billed_amount': 'alreadyBilledAmount',
    'subtotal': 'subtotal',
    'tax': 'tax',
    'total': 'total',
    'advance_pay_amount': 'advancePayAmount',
    'amount_due': 'amountDue',
}


def _parse_range(start: str, end: str, max_days: int) -> tuple:
    """Validate a YYYY-MM-DD date range (end inclusive) and return it as dates."""
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except (TypeError, ValueError):
        raise ValueError("start and end must be dates in YYYY-MM-DD format")
    if len(start) != 10 or len(end) != 10:
        raise ValueError("start and end must be dates in YYYY-MM-DD format")
    if start_date > end_date:
        raise ValueError("start must be on or before end")
    days = (end_date - start_date).days + 1
    if days > max_days:
        raise ValueError(f"date range is {days} days; the maximum is {max_days} days")
    return start_date, end_date


def _fetch_usage(start: str, end: str, max_days: int) -> List[Dict[str, Any]]:
    """Fetch daily usage buckets for an inclusive date range."""
    start_date, end_date = _parse_range(start, end, max_days)
    # The API only accepts RFC3339 instants, and a non-midnight start silently
    # returns an empty bucket, so always send midnight UTC.
    body = {
        'start': f"{start_date.isoformat()}T00:00:00Z",
        'end': f"{end_date.isoformat()}T00:00:00Z",
    }
    response = openapi_client.control_plane_api_request("/v2/usage/query", body_map=body, method="POST")
    return (response.get('data') or {}).get('results') or []


def _item_matches(item: Dict[str, Any], cluster_id: Optional[str], project_id: Optional[str]) -> bool:
    properties = item.get('properties') or {}
    if cluster_id and properties.get('clusterId') != cluster_id:
        return False
    if project_id and properties.get('projectId') != project_id:
        return False
    return True


def _decimal(value: Any) -> Decimal:
    # Go through str so float noise from JSON parsing doesn't leak into the sum.
    return Decimal(str(value or 0))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def _format_invoice(invoice: Dict[str, Any]) -> Dict[str, Any]:
    return {field: invoice.get(source) for field, source in _INVOICE_FIELDS.items()}


@zilliz_mcp.tool()
async def get_usage_summary(
    start: str,
    end: str,
    group_by: str = "cluster",
    cluster_id: Optional[str] = None,
    project_id: Optional[str] = None
) -> str:
    """
    Summarize Zilliz Cloud billing usage (cost) for the organization over a date range.
    Prefer this tool for cost questions such as "what did cluster X cost last month"
    or "what is my biggest cost driver". Requires an API key belonging to an
    organization owner or billing admin.

    Presenting results: report amounts exactly as returned and cite the currency; do not
    recompute them. Figures come straight from Zilliz Cloud billing data and have not
    been checked against invoices. Treat unit and unit_price as billing labels, not
    measurements: for compute, quantity can be CU-hours even when unit is "hour", so do
    not infer runtime, node counts or per-hour cluster rates from quantity or unit_price.
    If a figure looks implausible (e.g. one cluster's daily cost far above the rest of
    the org, or quantity / 24 far above the cluster's CU size), point it out as a
    possible billing data issue to confirm with Zilliz support rather than explaining it.

    Args:
        start: First day of the range in YYYY-MM-DD format (UTC)
        end: Last day of the range in YYYY-MM-DD format (UTC, inclusive). Maximum range is 366 days.
        group_by: How to group costs: "cluster", "project", "cost_type", "region" or "day" (default: "cluster")
        cluster_id: Only include usage for this cluster (optional)
        project_id: Only include usage for this project (optional)
    Returns:
        Dict with the total and groups sorted by amount (highest first). Amounts are in
        the returned currency, rounded to 2 decimal places after summing. Usage not tied
        to a cluster/project/region (e.g. org-level charges) is grouped as "unattributed".
        Example:
        {
            "start": "2026-09-01",
            "end": "2026-09-30",
            "currency": "USD",
            "group_by": "cluster",
            "total": 812.43,
            "groups": [
                {
                    "key": "in01-xxxxxxxxxxxxxxx",
                    "amount": 700.12,
                    "share_percent": 86.2,
                    "by_cost_type": {"compute": 650.0, "storage": 50.12}
                }
            ]
        }

    """
    try:
        # Log request
        logger.info(f"GET_USAGE_SUMMARY: start={start}, end={end}, group_by={group_by}, cluster_id={cluster_id}, project_id={project_id}")

        if group_by not in _GROUP_KEYS:
            raise ValueError(f"group_by must be one of: {', '.join(_GROUP_KEYS)}")
        key_of = _GROUP_KEYS[group_by]

        results = _fetch_usage(start, end, MAX_SUMMARY_DAYS)

        currencies = set()
        total = Decimal(0)
        group_amounts: Dict[str, Decimal] = defaultdict(Decimal)
        group_cost_types: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        for bucket in results:
            for item in bucket.get('items') or []:
                if not _item_matches(item, cluster_id, project_id):
                    continue
                amount = _decimal(item.get('amount'))
                key = key_of(bucket, item) or UNATTRIBUTED
                currencies.add(bucket.get('currency'))
                total += amount
                group_amounts[key] += amount
                group_cost_types[key][item.get('costType') or UNATTRIBUTED] += amount

        currencies.discard(None)
        if len(currencies) > 1:
            raise ValueError(f"usage spans multiple currencies: {', '.join(sorted(currencies))}")

        groups = []
        for key, amount in sorted(group_amounts.items(), key=lambda kv: kv[1], reverse=True):
            group = {
                'key': key,
                'amount': _money(amount),
                'share_percent': float((amount / total * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)) if total else 0.0,
            }
            if group_by != 'cost_type':
                group['by_cost_type'] = {
                    cost_type: _money(value)
                    for cost_type, value in sorted(group_cost_types[key].items(), key=lambda kv: kv[1], reverse=True)
                }
            groups.append(group)

        summary = {
            'start': start,
            'end': end,
            'currency': currencies.pop() if currencies else None,
            'group_by': group_by,
            'total': _money(total),
            'groups': groups,
        }

        # Log results
        logger.info(f"GET_USAGE_SUMMARY RESULT: total={summary['total']}, groups={len(groups)}")

        return json.dumps(summary)

    except Exception as e:
        logger.error(f"GET_USAGE_SUMMARY ERROR: {str(e)}")
        raise Exception(f"Failed to get usage summary: {str(e)}") from e


@zilliz_mcp.tool()
async def query_daily_usage(
    start: str,
    end: str,
    cluster_id: Optional[str] = None,
    project_id: Optional[str] = None
) -> str:
    """
    Query raw daily billing usage line items for the organization. Use this when you
    need per-day detail (e.g. to chart daily cost); for totals and breakdowns prefer
    get_usage_summary. Requires an API key belonging to an organization owner or
    billing admin.

    Presenting results: report amounts exactly as returned and cite the currency; do not
    recompute them. Figures come straight from Zilliz Cloud billing data and have not
    been checked against invoices. Treat unit and unit_price as billing labels, not
    measurements: for compute, quantity can be CU-hours even when unit is "hour", so do
    not infer runtime, node counts or per-hour cluster rates from quantity or unit_price.
    If a figure looks implausible (e.g. one cluster's daily cost far above the rest of
    the org, or quantity / 24 far above the cluster's CU size), point it out as a
    possible billing data issue to confirm with Zilliz support rather than explaining it.

    Args:
        start: First day of the range in YYYY-MM-DD format (UTC)
        end: Last day of the range in YYYY-MM-DD format (UTC, inclusive). Maximum range is 7 days; use cluster_id or project_id to keep results small.
        cluster_id: Only include line items for this cluster (optional)
        project_id: Only include line items for this project (optional)
    Returns:
        List of daily buckets. Each item's cost_type may be e.g. compute, storage, backup,
        read_vcu, write_vcu, storage_serverless, pipeline_tokens, query_cu_ondemand,
        indexing_cu, lakebase_storage, data_transfer_new, audit_log_cu. Amounts and unit
        prices are in the bucket's currency. When a filter is set, total covers only the
        matching items.
        Example:
        [
            {
                "day": "2026-09-16",
                "currency": "USD",
                "total": 10.6234567891,
                "items": [
                    {
                        "cost_type": "compute",
                        "properties": {"projectId": "proj-xxx", "regionId": "aws-us-west-2", "clusterId": "in01-xxx", "plan": "Enterprise", "cuType": "Performance-optimized"},
                        "quantity": 24.0,
                        "unit": "cu_hour",
                        "list_unit_price": 0.44,
                        "unit_price": 0.44,
                        "amount": 10.56
                    }
                ]
            }
        ]

    """
    try:
        # Log request
        logger.info(f"QUERY_DAILY_USAGE: start={start}, end={end}, cluster_id={cluster_id}, project_id={project_id}")

        results = _fetch_usage(start, end, MAX_RAW_DAYS)

        filtered = cluster_id or project_id
        days = []
        for bucket in results:
            items = [item for item in bucket.get('items') or [] if _item_matches(item, cluster_id, project_id)]
            total = float(sum((_decimal(item.get('amount')) for item in items), Decimal(0))) if filtered else bucket.get('total')
            days.append({
                'day': bucket.get('intervalStart', '')[:10],
                'currency': bucket.get('currency'),
                'total': total,
                'items': [
                    {
                        'cost_type': item.get('costType'),
                        'properties': item.get('properties') or {},
                        'quantity': item.get('quantity'),
                        'unit': item.get('unit'),
                        'list_unit_price': (item.get('listPrice') or {}).get('unitPrice'),
                        'unit_price': (item.get('price') or {}).get('unitPrice'),
                        'amount': item.get('amount'),
                    }
                    for item in items
                ],
            })

        # Log results
        logger.info(f"QUERY_DAILY_USAGE RESULT: returned {len(days)} days")

        return json.dumps(days)

    except Exception as e:
        logger.error(f"QUERY_DAILY_USAGE ERROR: {str(e)}")
        raise Exception(f"Failed to query daily usage: {str(e)}") from e


@zilliz_mcp.tool()
async def list_invoices(page_size: int = 10, current_page: int = 1) -> str:
    """
    List the organization's invoices in Zilliz Cloud. Requires an API key belonging to
    an organization owner or billing admin.

    Args:
        page_size: The number of invoices to include in each response (default: 10)
        current_page: The current page number (default: 1)
    Returns:
        Dict containing the invoice count and invoices
        Example:
        {
            "count": 1,
            "current_page": 1,
            "page_size": 10,
            "invoices": [
                {
                    "invoice_id": "inv-xxxxxxxxxxxxxxx",
                    "org_id": "org-xxxxxxxxxxxxxxx",
                    "period_start": "2026-08-01T00:00:00Z",
                    "period_end": "2026-08-31T23:59:59Z",
                    "invoice_date": "2026-09-01T00:00:00Z",
                    "due_date": "2026-09-15T00:00:00Z",
                    "currency": "USD",
                    "status": "paid",
                    "usage_amount": 100.5,
                    "credits_applied": 10.0,
                    "already_billed_amount": 0,
                    "subtotal": 90.5,
                    "tax": 0,
                    "total": 90.5,
                    "advance_pay_amount": 0,
                    "amount_due": 0
                }
            ]
        }
        status is one of: unbilled, unconfirmed, disputed, unpaid, overdue, paid, free.
        Amounts are whole units of the invoice currency (e.g. 883850 means $883,850), not cents.
        The current period's invoice has status "unbilled" and its amounts are still accruing.

    """
    try:
        # Log request
        logger.info(f"LIST_INVOICES: page_size={page_size}, current_page={current_page}")

        params = {
            'pageSize': page_size,
            'currentPage': current_page
        }

        response = openapi_client.control_plane_api_request("/v2/invoices", params_map=params)
        data = response.get('data') or {}
        invoices = [_format_invoice(invoice) for invoice in data.get('invoices') or []]

        result = {
            'count': data.get('count', len(invoices)),
            'current_page': data.get('currentPage', current_page),
            'page_size': data.get('pageSize', page_size),
            'invoices': invoices,
        }

        # Log results
        logger.info(f"LIST_INVOICES RESULT: found {len(invoices)} invoices")

        return json.dumps(result)

    except Exception as e:
        logger.error(f"LIST_INVOICES ERROR: {str(e)}")
        raise Exception(f"Failed to list invoices: {str(e)}") from e


@zilliz_mcp.tool()
async def describe_invoice(invoice_id: str) -> str:
    """
    Describe an invoice in detail. Requires an API key belonging to an organization
    owner or billing admin.

    Args:
        invoice_id: ID of the invoice to describe (from list_invoices)
    Returns:
        Dict containing the invoice, with the same fields as each entry of list_invoices.
        The API currently returns a server error for the current "unbilled" invoice;
        use list_invoices to read that one.

    """
    try:
        # Log request
        logger.info(f"DESCRIBE_INVOICE: invoice_id={invoice_id}")

        response = openapi_client.control_plane_api_request(f"/v2/invoices/{invoice_id}", method="GET")
        invoice = _format_invoice(response.get('data') or {})

        # Log results
        logger.info(f"DESCRIBE_INVOICE RESULT: status={invoice['status']}, total={invoice['total']}")

        return json.dumps(invoice)

    except Exception as e:
        logger.error(f"DESCRIBE_INVOICE ERROR: {str(e)}")
        raise Exception(f"Failed to describe invoice: {str(e)}") from e
