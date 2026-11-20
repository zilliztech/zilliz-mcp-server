"""Tool descriptions must match limits and enums observed on Zilliz Cloud (see PR for the calls)."""

import inspect

from zilliz_mcp_server.tools.milvus import milvus_tools as mt
from zilliz_mcp_server.tools.zilliz import zilliz_tools as zt


def _doc(fn):
    return inspect.getdoc(fn) or ""


def test_search_window_is_16384_not_100():
    # offset+topk outside [1, 16384] is rejected by the server; limit=150 is accepted.
    doc = _doc(mt.search)
    assert "less than 100" not in doc
    assert doc.count("limit + offset must be at most 16,384") == 2


def test_query_window_is_inclusive_16384():
    # query limit=16384 is accepted; 16385 is rejected.
    assert _doc(mt.query).count("limit + offset must be at most 16,384") == 2


def test_hybrid_search_limit_does_not_mention_missing_offset_param():
    doc = _doc(mt.hybrid_search)
    assert "after reranking (at most 16,384)" in doc
    assert "offset" not in inspect.signature(mt.hybrid_search).parameters


def test_consistency_levels_match_server_enum():
    # Server: "consistencyLevel can only be [Strong, Session, Bounded, Eventually, Customized], default: Bounded"
    for fn in (mt.search, mt.hybrid_search):
        assert "Strong, Session, Bounded, Eventually, Customized; the server default is Bounded" in _doc(fn)


def test_list_clusters_page_size_range():
    # Server: "The parameter value for 'pageSize' should be between 1 and 100."
    assert "range 1-100" in _doc(zt.list_clusters)
