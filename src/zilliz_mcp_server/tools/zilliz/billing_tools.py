"""Zilliz Control Plane billing tools."""

import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional
from zilliz_mcp_server.common import hints, openapi_client
from zilliz_mcp_server.app import read_tool
from zilliz_mcp_server.common.budget import RESULT_BUDGET

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# The usage API returns the whole range in one response (~85 KB per day for an
# org with ~200 clusters), so cap how much we pull through the server and into the agent.
MAX_SUMMARY_DAYS = 366
MAX_RAW_DAYS = 31
# Org-wide usage is large (measured ~85 KB of JSON per day for an org with ~200 clusters),
# so cap what reaches the model.
DEFAULT_GROUP_LIMIT = 20
MAX_GROUP_LIMIT = 200
MAX_LINE_ITEMS = 200
MAX_INVOICE_PAGE_SIZE = 100
# List Invoices returns this business code ("An unknown error occurred") when pageSize or
# currentPage is missing.
INVOICE_UNKNOWN_ERROR_CODE = 20011
# Observed (one organization, not a documented limit): ranges starting on or after this day
# returned daily usage; earlier ranges failed with code 3 ("Bad request", no detail) or came back
# empty. It is NOT enforced locally (other organizations may have older data); it is only used to
# word the error for code 3 and the note on an empty early result. Invoices go back further.
EARLIEST_USAGE_DATE = date(2025, 3, 1)
USAGE_BAD_REQUEST_CODE = 3
EARLY_EMPTY_NOTE = (
    "No usage was returned for this range. Ranges before {boundary} were observed to be unavailable "
    "from the usage API, so empty does not mean zero spend: read invoiced totals with list_invoices "
    "for those months.")

UNATTRIBUTED = "unattributed"


def budget_size(obj: Any) -> int:
    """Bytes of JSON, as counted against RESULT_BUDGET."""
    return len(json.dumps(obj))

INVOICE_AMOUNT_UNIT_NOTE = (
    "Invoice amounts are integers in whole units of 'currency' (e.g. USD dollars, not cents), "
    "rounded by billing. usage_amount is close to, but not exactly, the sum of daily usage for "
    "the period; quote invoice figures for what was billed."
)

_GROUP_KEYS = {
    'cluster': lambda bucket, item: item.get('properties', {}).get('clusterId'),
    'project': lambda bucket, item: item.get('properties', {}).get('projectId'),
    'region': lambda bucket, item: item.get('properties', {}).get('regionId'),
    'cost_type': lambda bucket, item: item.get('costType'),
    'day': lambda bucket, item: bucket.get('intervalStart', '')[:10],
    'month': lambda bucket, item: bucket.get('intervalStart', '')[:7],
}
_DATE_GROUPS = ('day', 'month')

# group_by="day" over more than this many days leaves out each day's by_cost_type: a year of
# daily breakdowns is ~90 KB, more than MCP clients reliably show in full.
LONG_RANGE_DAYS = 92

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


def early_empty_note(start: str, results: List[Dict[str, Any]]) -> Optional[str]:
    """Note for a range that starts before the observed boundary and returned no line items."""
    if start >= EARLIEST_USAGE_DATE.isoformat() or any(bucket.get('items') for bucket in results):
        return None
    return EARLY_EMPTY_NOTE.format(boundary=EARLIEST_USAGE_DATE)


def usage_tool_error(tool: str, exc: Exception, ctx: Dict[str, Any]) -> hints.StructuredToolError:
    """tool_error for usage tools; the server's bare 'Bad request' (code 3) gets an actionable hint.

    Every code 3 is treated as a possibly unavailable date range: the API gives no reason, and the
    only cause observed is a range starting too early.
    ctx must hold the start/end argument names used by the tool (start/end or base_*/target_*).
    """
    structured = hints.tool_error(tool, exc, ctx)
    if getattr(exc, 'code', None) != USAGE_BAD_REQUEST_CODE:
        return structured
    boundary = EARLIEST_USAGE_DATE.isoformat()
    starts = {k: v for k, v in ctx.items() if k.endswith('start') and isinstance(v, str)}
    early = {k: v for k, v in starts.items() if v[:10] < boundary}
    field = next(iter(early), next(iter(starts), 'start'))
    steps = []
    if early and all(str(ctx.get(k.replace('start', 'end'), '9999')) >= boundary for k in early):
        retry = {**ctx, **{k: boundary for k in early}}
        steps.append(hints.step(tool, f"Retry with start moved to {boundary} (observed to work).", **retry))
    steps.append(hints.step('list_invoices', 'Invoices cover months the usage API does not serve.',
                            page_size=24, current_page=1))
    payload = {**structured.payload, 'error': 'INVALID_ARGUMENT', 'field': field, 'got': starts.get(field),
               'message': (f"The usage API rejected this date range with 'Bad request' and gave no reason. "
                           f"Observed: earlier dates are not queryable; on the organization tested, usage was "
                           f"available from {boundary} onward (the limit may differ per organization)."),
               'expected': f"a range the usage API serves (observed: starting on or after {boundary})",
               'fix': (f"Read invoiced totals for the requested months with list_invoices, and tell the user "
                       f"daily usage is not available for that range. If {field} is before {boundary}, "
                       f"retrying with {field}={boundary} was observed to work."),
               'next_steps': steps}
    return hints.StructuredToolError({k: v for k, v in payload.items() if v not in (None, "", [], {})})


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


@read_tool()
async def get_usage_summary(
    start: str,
    end: str,
    group_by: str = "cluster",
    cluster_id: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = DEFAULT_GROUP_LIMIT
) -> str:
    """
    Summarize Zilliz Cloud billing usage (cost) for the organization over a date range.
    Prefer this tool for cost questions such as "what did cluster X cost last month"
    or "what is my biggest cost driver". Requires an API key with the Organization
    Owner or Organization Billing Admin role (a personal key uses
    its user's role; a customized key has its own role). Otherwise it fails with error
    PERMISSION_DENIED; relay its fix and message_for_admin to the user instead of
    estimating costs. AUTH_FAILED means the key itself is invalid, not a missing role.

    Usage is the metered cost (quantity x unit price) BEFORE credits, discounts, advance
    pay and tax are applied, so it can differ from what was invoiced or paid. Use
    list_invoices for invoiced totals (usage_amount, credits_applied, total).

    Presenting results: report amounts exactly as returned and cite the currency; do not
    recompute them. Figures come straight from Zilliz Cloud billing data and have not
    been checked against invoices. Treat unit and unit_price as billing labels, not
    measurements: for compute, quantity can be CU-hours even when unit is "hour", so do
    not infer runtime, node counts or per-hour cluster rates from quantity or unit_price.
    If a figure looks implausible (e.g. one cluster's daily cost far above the rest of
    the org, or quantity / 24 far above the cluster's CU size), point it out as a
    possible billing data issue to confirm with Zilliz support rather than explaining it.

    Args:
        start: First day of the range in YYYY-MM-DD format (UTC). Older dates may not be
            queryable (observed: from 2025-03-01 on); for earlier months use list_invoices
        end: Last day of the range in YYYY-MM-DD format (UTC, inclusive). Maximum range is 366 days.
        group_by: How to group costs: "cluster", "project", "cost_type", "region", "day" or "month" (default: "cluster").
                  For ranges over 92 days prefer "month"; "day" then leaves out each day's by_cost_type.
                  Month groups only cover days inside start..end, so the first and last month
                  are partial unless the range starts on the 1st / ends on the last day of a month.
        cluster_id: Only include usage for this cluster (optional)
        project_id: Only include usage for this project (optional)
        limit: Maximum number of groups to return (default 20, max 200). Smaller groups are
               rolled up into one "other" entry so the total still adds up. Ignored for
               group_by="day" and "month", which always return every period in date order.
    Returns:
        Dict with the total and groups sorted by amount (highest first; by date for
        group_by="day" / "month"). Amounts are decimal
        values in whole units of the returned currency (e.g. 12.34 = 12.34 USD, not cents),
        rounded to 2 decimal places after summing. Usage not tied to a cluster/project/region
        (e.g. org-level charges) is grouped as "unattributed". group_count is the number of
        groups before the limit; when it exceeds the limit the last entry has key "other"
        and other_group_count. Narrow with cluster_id / project_id or a coarser group_by
        (project, cost_type) instead of raising the limit.
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
        if not isinstance(limit, int) or not 1 <= limit <= MAX_GROUP_LIMIT:
            raise ValueError(f"limit must be an integer from 1 to {MAX_GROUP_LIMIT}")
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

        if group_by in _DATE_GROUPS:
            ranked = sorted(group_amounts.items())
            kept, rest = ranked, []
        else:
            ranked = sorted(group_amounts.items(), key=lambda kv: kv[1], reverse=True)
            kept, rest = ranked[:limit], ranked[limit:]
        notes = []
        with_cost_types = group_by != 'cost_type'
        if group_by == 'day' and len(results) > LONG_RANGE_DAYS:
            with_cost_types = False
            notes.append(f"by_cost_type is left out per day for ranges over {LONG_RANGE_DAYS} days to keep the "
                         "result small; use group_by=month for monthly cost by cost_type, or a range of "
                         f"{LONG_RANGE_DAYS} days or less for daily detail.")
        if group_by == 'month':
            start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
            partial = [m for m, is_partial in (
                (start[:7], start_day.day != 1),
                (end[:7], (end_day + timedelta(days=1)).day != 1),
            ) if is_partial]
            if partial:
                notes.append(f"Partial month(s) {', '.join(sorted(set(partial)))}: only days from {start} to {end} "
                             "are counted, so do not compare them with full months.")
        empty_note = early_empty_note(start, results)
        if empty_note:
            notes.append(empty_note)

        def share(amount: Decimal) -> float:
            return float((amount / total * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)) if total else 0.0

        groups = []
        for key, amount in kept:
            group = {
                'key': key,
                'amount': _money(amount),
            }
            if group_by not in _DATE_GROUPS:  # a day's share of the range says little
                group['share_percent'] = share(amount)
            if with_cost_types:
                group['by_cost_type'] = {
                    cost_type: _money(value)
                    for cost_type, value in sorted(group_cost_types[key].items(), key=lambda kv: kv[1], reverse=True)
                }
            groups.append(group)
        if rest:
            rest_amount = sum((amount for _, amount in rest), Decimal(0))
            groups.append({'key': 'other', 'amount': _money(rest_amount), 'share_percent': share(rest_amount),
                           'other_group_count': len(rest)})

        summary = {
            'start': start,
            'end': end,
            'currency': currencies.pop() if currencies else None,
            'group_by': group_by,
            'total': _money(total),
            'group_count': len(ranked),
            'groups': groups,
        }

        # Log results
        logger.info(f"GET_USAGE_SUMMARY RESULT: total={summary['total']}, groups={len(groups)}")

        return hints.ok(summary, None, notes)

    except Exception as e:
        logger.error(f"GET_USAGE_SUMMARY ERROR: {str(e)}")
        raise usage_tool_error("get_usage_summary", e,
                               {'start': start, 'end': end, 'group_by': group_by,
                                'cluster_id': cluster_id, 'project_id': project_id}) from e


@read_tool()
async def query_daily_usage(
    start: str,
    end: str,
    cluster_id: Optional[str] = None,
    project_id: Optional[str] = None
) -> str:
    """
    Query daily billing usage. Use this when you need per-day detail (e.g. to chart daily
    cost); for totals and breakdowns prefer get_usage_summary. Without cluster_id or
    project_id it returns only each day's total and cost by cost_type (org-wide line items
    are far too large to return). With a filter it also returns that scope's line items
    (at most 200 across the range; items_truncated tells you when more were cut).
    Requires an API key with the Organization Owner or Organization Billing Admin role;
    otherwise it fails with error PERMISSION_DENIED.

    Amounts are metered usage BEFORE credits, discounts, advance pay and tax, not the
    invoiced amount. Use list_invoices for invoiced totals.

    Presenting results: report amounts exactly as returned and cite the currency; do not
    recompute them. Figures come straight from Zilliz Cloud billing data and have not
    been checked against invoices. Treat unit and unit_price as billing labels, not
    measurements: for compute, quantity can be CU-hours even when unit is "hour", so do
    not infer runtime, node counts or per-hour cluster rates from quantity or unit_price.
    If a figure looks implausible (e.g. one cluster's daily cost far above the rest of
    the org, or quantity / 24 far above the cluster's CU size), point it out as a
    possible billing data issue to confirm with Zilliz support rather than explaining it.

    Args:
        start: First day of the range in YYYY-MM-DD format (UTC). Older dates may not be
            queryable (observed: from 2025-03-01 on); for earlier months use list_invoices
        end: Last day of the range in YYYY-MM-DD format (UTC, inclusive). Maximum range is 31 days.
        cluster_id: Only include line items for this cluster (optional)
        project_id: Only include line items for this project (optional)
    Returns:
        List of daily buckets with day, currency, total and by_cost_type; plus items when a
        filter is set. cost_type may be e.g. compute, storage, backup, read_vcu, write_vcu,
        storage_serverless, stage, pipeline_tokens, query_cu_ondemand, indexing_cu,
        lakebase_storage, lakebase_storage_request, data_transfer_new, audit_log_cu.
        Amounts and unit prices are decimal values in whole units of the bucket's currency
        (e.g. USD, not cents); amount = quantity x unit_price. When a filter is set, total
        covers only the matching items. Item properties omit keys whose value is null.
        Example:
        [
            {
                "day": "2026-09-16",
                "currency": "USD",
                "total": 10.6234567891,
                "by_cost_type": {"compute": 10.56, "storage": 0.06},
                "items": [
                    {
                        "cost_type": "compute",
                        "properties": {"projectId": "proj-xxx", "regionId": "aws-us-west-2", "clusterId": "in01-xxx", "cuType": "Performance-optimized"},
                        "quantity": 24.0,
                        "unit": "hour",
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
            by_cost_type: Dict[str, Decimal] = defaultdict(Decimal)
            for item in items:
                by_cost_type[item.get('costType') or UNATTRIBUTED] += _decimal(item.get('amount'))
            day = {
                'day': bucket.get('intervalStart', '')[:10],
                'currency': bucket.get('currency'),
                'total': total,
                'by_cost_type': {k: _money(v) for k, v in sorted(by_cost_type.items(), key=lambda kv: kv[1], reverse=True)},
            }
            if filtered:
                day['items'] = [
                    {
                        'cost_type': item.get('costType'),
                        'properties': {k: v for k, v in (item.get('properties') or {}).items() if v is not None},
                        'quantity': item.get('quantity'),
                        'unit': item.get('unit'),
                        'list_unit_price': (item.get('listPrice') or {}).get('unitPrice'),
                        'unit_price': (item.get('price') or {}).get('unitPrice'),
                        'amount': item.get('amount'),
                    }
                    for item in items
                ]
            days.append(day)

        # Cap line items by count (MAX_LINE_ITEMS) and by size (RESULT_BUDGET), keeping the newest
        # days' items first; daily totals and by_cost_type always stay for every day.
        notes = []
        if filtered:
            count_left = MAX_LINE_ITEMS
            used = budget_size([{k: v for k, v in d.items() if k != 'items'} for d in days])
            for day in reversed(days):
                items = day['items']
                keep = 0
                for item in items:
                    cost = budget_size(item) + 2  # item plus separator
                    if keep >= count_left or used + cost > RESULT_BUDGET:
                        break
                    used += cost
                    keep += 1
                count_left -= keep
                if keep < len(items):
                    day['items_truncated'] = len(items) - keep
                    day['items'] = items[:keep]
                    used += len(', "items_truncated": 000000')
            # The running size is an estimate; drop items from the oldest days until it really fits.
            while budget_size(days) > RESULT_BUDGET:
                day = next((d for d in days if d.get('items')), None)
                if day is None:
                    break
                day['items'].pop()
                day['items_truncated'] = day.get('items_truncated', 0) + 1
            if any('items_truncated' in d for d in days):
                notes.append(f"Line items were capped ({MAX_LINE_ITEMS} items or "
                             f"{RESULT_BUDGET // 1000} KB), keeping the newest days first; see "
                             f"items_truncated per day. Daily totals and by_cost_type are complete "
                             f"for every day. Narrow start/end to see the earlier days' items.")

        # Log results
        logger.info(f"QUERY_DAILY_USAGE RESULT: returned {len(days)} days")

        empty_note = early_empty_note(start, results)
        if empty_note:
            notes.insert(0, empty_note)
        return hints.ok(days, notes=notes)

    except Exception as e:
        logger.error(f"QUERY_DAILY_USAGE ERROR: {str(e)}")
        raise usage_tool_error("query_daily_usage", e,
                               {'start': start, 'end': end, 'cluster_id': cluster_id,
                                'project_id': project_id}) from e


@read_tool()
async def list_invoices(page_size: int = 10, current_page: int = 1) -> str:
    """
    List the organization's invoices in Zilliz Cloud. Requires an API key belonging to
    an organization owner or billing admin; otherwise it fails with error PERMISSION_DENIED.

    Args:
        page_size: The number of invoices to include in each response (1-100, default: 10)
        current_page: The current page number (starts at 1, default: 1)
    Returns:
        Dict containing the invoice count and invoices
        Example:
        {
            "count": 1,
            "current_page": 1,
            "page_size": 10,
            "amount_unit_note": "Invoice amounts are integers in whole units of 'currency' ...",
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
                    "usage_amount": 101,
                    "credits_applied": 10,
                    "already_billed_amount": 0,
                    "subtotal": 91,
                    "tax": 0,
                    "total": 91,
                    "advance_pay_amount": 0,
                    "amount_due": 0
                }
            ]
        }
        status is one of: unbilled, unconfirmed, disputed, unpaid, overdue, paid, void.
        Amounts are integers in whole units of currency (e.g. 91 = 91 USD, not cents).
        usage_amount is metered usage before credits; total / amount_due reflect credits,
        advance pay and tax.
        The current period's invoice has status "unbilled" and its amounts are still accruing.
        count is the total number of invoices; page with current_page if count > page_size.

    """
    try:
        # Log request
        logger.info(f"LIST_INVOICES: page_size={page_size}, current_page={current_page}")

        # The API needs both parameters; without either it fails with code 20011 ("unknown error").
        if not isinstance(page_size, int) or not 1 <= page_size <= MAX_INVOICE_PAGE_SIZE:
            raise ValueError(f"page_size must be an integer from 1 to {MAX_INVOICE_PAGE_SIZE}")
        if not isinstance(current_page, int) or current_page < 1:
            raise ValueError("current_page must be an integer >= 1")
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
            'amount_unit_note': INVOICE_AMOUNT_UNIT_NOTE,
            'invoices': invoices,
        }

        # Log results
        logger.info(f"LIST_INVOICES RESULT: found {len(invoices)} invoices")

        return hints.ok(result)

    except Exception as e:
        logger.error(f"LIST_INVOICES ERROR: {str(e)}")
        ctx = {'page_size': page_size, 'current_page': current_page}
        structured = hints.tool_error("list_invoices", e, ctx)
        if getattr(e, 'code', None) == INVOICE_UNKNOWN_ERROR_CODE:
            structured = hints.StructuredToolError({
                **structured.payload,
                'fix': "The billing API returned its generic 'unknown error' (code 20011). It returns this "
                       "when pageSize or currentPage is missing; this tool always sends both, so retry once. "
                       "If it persists, it is a server-side problem: tell the user to check the Billing page "
                       "in the Zilliz Cloud console or contact Zilliz support.",
                'next_steps': [hints.step('list_invoices', 'Retry once with explicit paging.',
                                          page_size=page_size, current_page=current_page)],
            })
        raise structured from e


@read_tool()
async def describe_invoice(invoice_id: str) -> str:
    """
    Describe one invoice. It returns the same fields as an entry of list_invoices, so prefer
    list_invoices (with page_size up to 100) unless you only have the id: this endpoint can
    take from several seconds to over a minute. Requires an API key with the Organization
    Owner or Organization Billing Admin role; otherwise it fails with error PERMISSION_DENIED.

    Args:
        invoice_id: ID of the invoice to describe (from list_invoices)
    Returns:
        Dict containing the invoice, with the same fields as each entry of list_invoices.
        Amounts are integers in whole units of currency (see amount_unit_note).

    """
    try:
        # Log request
        logger.info(f"DESCRIBE_INVOICE: invoice_id={invoice_id}")

        response = openapi_client.control_plane_api_request(f"/v2/invoices/{invoice_id}", method="GET")
        invoice = _format_invoice(response.get('data') or {})
        invoice['amount_unit_note'] = INVOICE_AMOUNT_UNIT_NOTE

        # Log results
        logger.info(f"DESCRIBE_INVOICE RESULT: status={invoice['status']}, total={invoice['total']}")

        return hints.ok(invoice)

    except Exception as e:
        logger.error(f"DESCRIBE_INVOICE ERROR: {str(e)}")
        raise hints.tool_error("describe_invoice", e, {'invoice_id': invoice_id}) from e
