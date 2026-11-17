"""Keep row-shaped tool results small enough for MCP clients to read in full.

MCP clients commonly truncate long tool output. A query that returns full rows with a 1024-dim
float vector is ~14 KB per row, so 100 rows is over 1 MB and the client only shows the start of it.
Results are trimmed to RESULT_BUDGET bytes of JSON and the caller tells the model what was cut and
how to fetch the rest.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

# Bytes of JSON allowed for the rows (data) in one tool result. Clients were observed to cut tool
# output at about 50 KB; this leaves room for notes / next_steps in the same envelope.
RESULT_BUDGET = 45_000

# A list of at least this many numbers is treated as a vector, not a scalar ARRAY.
_VECTOR_MIN_LEN = 32
# Longest string kept verbatim when a single row alone exceeds the budget.
_MAX_STR = 2_000

VECTOR_TYPES = ("FloatVector", "BinaryVector", "Float16Vector", "BFloat16Vector",
                "SparseFloatVector", "Int8Vector")


def _size(obj: Any) -> int:
    return len(json.dumps(obj))


def is_vector_value(value: Any) -> bool:
    """True for values shaped like an embedding (long list of numbers, or a sparse vector)."""
    if isinstance(value, list) and len(value) >= _VECTOR_MIN_LEN:
        return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value[:_VECTOR_MIN_LEN])
    if isinstance(value, dict) and len(value) >= _VECTOR_MIN_LEN:
        return all(isinstance(v, (int, float)) for v in list(value.values())[:_VECTOR_MIN_LEN])
    return False


def vector_keys(rows: List[Any]) -> List[str]:
    """Keys whose value looks like a vector in any of the rows (sorted)."""
    keys = set()
    for row in rows:
        if isinstance(row, dict):
            keys.update(k for k, v in row.items() if is_vector_value(v))
    return sorted(keys)


def scalar_fields(describe_data: Dict[str, Any]) -> Optional[List[str]]:
    """Non-vector field names from a describe_collection response, or None if unknown.

    Dynamic-field collections also get "$meta" so dynamic keys are still returned.
    """
    fields = (describe_data or {}).get("fields")
    if not isinstance(fields, list) or not fields:
        return None
    names = [f.get("name") for f in fields
             if isinstance(f, dict) and f.get("name") and f.get("type") not in VECTOR_TYPES]
    if not names or len(names) == len(fields):
        return None  # nothing to exclude; keep the API default
    if describe_data.get("enableDynamicField"):
        names.append("$meta")
    return names


def _shrink_row(row: Any) -> Any:
    """Shorten oversized values of one row so that at least one row fits."""
    if not isinstance(row, dict):
        return row
    out = {}
    for k, v in row.items():
        if is_vector_value(v):
            out[k] = f"<{len(v)}-dim vector omitted>"
        elif isinstance(v, str) and len(v) > _MAX_STR:
            out[k] = v[:_MAX_STR] + f"... <{len(v) - _MAX_STR} more chars>"
        else:
            out[k] = v
    return out


def fit_rows(rows: List[Any], budget: int = RESULT_BUDGET) -> Tuple[List[Any], Optional[Dict[str, Any]]]:
    """Return (rows that fit in budget, info) where info is None if nothing was cut.

    info: {"returned", "total", "bytes_total", "vector_keys", "shrunk"}.
    """
    if not isinstance(rows, list) or _size(rows) <= budget:
        return rows, None
    kept: List[Any] = []
    used = 2  # "[]"
    for row in rows:
        n = _size(row) + 2  # ", "
        if used + n > budget:
            break
        kept.append(row)
        used += n
    shrunk = False
    if not kept and rows:
        kept, shrunk = [_shrink_row(rows[0])], True
    return kept, {"returned": len(kept), "total": len(rows), "bytes_total": _size(rows),
                  "vector_keys": vector_keys(rows[:5]), "shrunk": shrunk}


def trimmed_note(tool: str, info: Dict[str, Any]) -> str:
    """One note telling the model what fit_rows cut."""
    msg = (f"Result trimmed to fit the response size budget: showing {info['returned']} of "
           f"{info['total']} rows (full result was {info['bytes_total']:,} bytes of JSON; "
           f"clients truncate long tool output).")
    if info["shrunk"]:
        msg += " The single row shown has long values shortened."
    if info["vector_keys"]:
        msg += (f" Vector field(s) {', '.join(info['vector_keys'])} take most of the space; "
                f"omit them from output_fields unless you need the raw embeddings.")
    else:
        msg += f" Fetch the rest with offset, a smaller limit or fewer output_fields."
    return msg


def leaner_fields(rows: List[Any], output_fields: Optional[List[str]]) -> Optional[List[str]]:
    """output_fields without the vector keys, or None if that would not change anything."""
    vk = set(vector_keys(rows[:5]))
    if not vk:
        return None
    if output_fields and "*" not in output_fields:
        lean = [f for f in output_fields if f not in vk]
    else:
        first = next((r for r in rows if isinstance(r, dict)), {})
        lean = [k for k in first if k not in vk and k != "distance"]
    return lean or None
