"""
混合检索模块单元测试

覆盖：
  - _parse_chromadb_result: ChromaDB 原始结果解析
  - keyword_match_search: 关键词文本匹配检索
  - hybrid_search: 混合向量 + 关键词检索
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


# ==================== _parse_chromadb_result 测试 ====================

class TestParseChromaDBResult:
    """_parse_chromadb_result 函数测试"""

    def test_normal_result_parsing(self):
        """正常结果解析（含 ids, documents, metadatas, distances）"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["doc1", "doc2"]],
            "documents": [["这是文档一的内容", "这是文档二的内容"]],
            "metadatas": [
                [
                    {"kb_type": "faq", "source_type": "manual", "source_id": "src_001"},
                    {"kb_type": "product", "source_type": "auto", "source_id": "src_002"},
                ]
            ],
            "distances": [[0.2, 0.6]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 2

        # 第一条文档
        assert result[0]["content"] == "这是文档一的内容"
        assert result[0]["score"] == round(1.0 - 0.2, 4)  # 0.8
        assert result[0]["kb_type"] == "faq"
        assert result[0]["source"] == "manual"
        assert result[0]["source_id"] == "src_001"
        assert result[0]["metadata"]["kb_type"] == "faq"

        # 第二条文档
        assert result[1]["content"] == "这是文档二的内容"
        assert result[1]["score"] == round(1.0 - 0.6, 4)  # 0.4
        assert result[1]["kb_type"] == "product"
        assert result[1]["source"] == "auto"
        assert result[1]["source_id"] == "src_002"

    def test_empty_dict_result(self):
        """空 dict 结果解析 → 返回 []"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        result = _parse_chromadb_result({})
        assert result == []

    def test_none_result(self):
        """None 结果解析 → 返回 []"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        result = _parse_chromadb_result(None)
        assert result == []

    def test_no_ids_result(self):
        """没有 ids 的结果 → 返回 []"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "documents": [["内容"]],
            "metadatas": [[{}]],
            "distances": [[0.5]],
        }
        result = _parse_chromadb_result(raw)
        assert result == []

    def test_empty_ids_list_result(self):
        """ids 第一层为空列表 → 返回 []"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        result = _parse_chromadb_result(raw)
        assert result == []

    def test_similarity_calculation(self):
        """验证 similarity 计算（1.0 - distance）"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["doc_a"]],
            "documents": [["测试内容"]],
            "metadatas": [[{"kb_type": "rule"}]],
            "distances": [[0.35]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 1
        # similarity = 1.0 - 0.35 = 0.65
        assert result[0]["score"] == round(1.0 - 0.35, 4)

    def test_distance_exactly_one(self):
        """distance = 1.0 时 similarity = 0.0"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["doc_x"]],
            "documents": [["无关内容"]],
            "metadatas": [[{"kb_type": "public"}]],
            "distances": [[1.0]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 1
        assert result[0]["score"] == 0.0

    def test_distance_exactly_zero(self):
        """distance = 0.0 时 similarity = 1.0"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["doc_perfect"]],
            "documents": [["完全匹配"]],
            "metadatas": [[{"kb_type": "faq"}]],
            "distances": [[0.0]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 1
        assert result[0]["score"] == 1.0

    def test_kb_type_extraction_from_metadata(self):
        """验证 metadata 中 kb_type 的正确提取"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["doc_faq", "doc_product", "doc_rule"]],
            "documents": [["FAQ内容", "商品内容", "规则内容"]],
            "metadatas": [
                [
                    {"kb_type": "faq"},
                    {"kb_type": "product"},
                    {"kb_type": "rule"},
                ]
            ],
            "distances": [[0.1, 0.2, 0.3]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 3
        assert result[0]["kb_type"] == "faq"
        assert result[1]["kb_type"] == "product"
        assert result[2]["kb_type"] == "rule"

    def test_source_fallback_to_kb_type(self):
        """source 字段回退：没有 source_type 时使用 kb_type"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["doc_no_source"]],
            "documents": [["测试"]],
            "metadatas": [[{"kb_type": "public"}]],
            "distances": [[0.1]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 1
        # metadata 中没有 source_type，应回退到 kb_type
        assert result[0]["source"] == "public"

    def test_source_id_fallback_to_id(self):
        """source_id 回退：没有 source_id 时使用 ChromaDB id"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["chroma_id_123"]],
            "documents": [["内容"]],
            "metadatas": [[{"kb_type": "faq"}]],
            "distances": [[0.5]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 1
        # metadata 中没有 source_id，应回退到 ids[i]
        assert result[0]["source_id"] == "chroma_id_123"

    def test_missing_distances_default(self):
        """缺少 distances 字段时使用默认值 1.0 → similarity = 0.0"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["doc_default"]],
            "documents": [["默认距离"]],
            "metadatas": [[{"kb_type": "faq"}]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 1
        assert result[0]["score"] == 0.0

    def test_none_content_handling(self):
        """content 为 None 时转换为空字符串"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["doc_none"]],
            "documents": [[None]],
            "metadatas": [[{"kb_type": "faq"}]],
            "distances": [[0.1]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 1
        assert result[0]["content"] == ""

    def test_missing_metadatas_default(self):
        """缺少 metadatas 字段时使用空 dict → kb_type 为 unknown"""
        from backend.retrieval.hybrid_search import _parse_chromadb_result

        raw = {
            "ids": [["doc_no_meta"]],
            "documents": [["无元数据"]],
            "distances": [[0.1]],
        }

        result = _parse_chromadb_result(raw)

        assert len(result) == 1
        assert result[0]["kb_type"] == "unknown"
        assert result[0]["source"] == "unknown"


# ==================== keyword_match_search 测试 ====================

class TestKeywordMatchSearch:
    """keyword_match_search 函数测试（mock ChromaDB collection）"""

    def test_normal_keyword_match(self):
        """正常关键词匹配"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import keyword_match_search

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["k1", "k2", "k3"],
            "documents": [
                "如何退货退款流程说明",
                "商品尺寸对照表查询",
                "优惠券使用规则详解",
            ],
            "metadatas": [
                {"source_type": "manual"},
                {"source_type": "auto"},
                {"source_type": "manual"},
            ],
        }

        with patch("backend.retrieval.hybrid_search.get_collection", return_value=mock_collection):
            results = keyword_match_search(
                keywords=["退货", "退款"],
                tenant_id="tenant_001",
                kb_types=["faq"],
                min_hits=1,
            )

        assert len(results) > 0
        # 第一条约含 "退货""退款"两个关键词
        assert results[0]["content"] == "如何退货退款流程说明"
        assert results[0]["_keyword_hits"] >= 1
        assert results[0]["kb_type"] == "faq"
        assert "score" in results[0]

    def test_keyword_not_match(self):
        """关键词不匹配 → 返回 []"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import keyword_match_search

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["k1", "k2"],
            "documents": [
                "商品介绍页面",
                "物流配送说明",
            ],
            "metadatas": [
                {},
                {},
            ],
        }

        with patch("backend.retrieval.hybrid_search.get_collection", return_value=mock_collection):
            results = keyword_match_search(
                keywords=["退款", "退货"],
                tenant_id="tenant_001",
                kb_types=["faq"],
                min_hits=1,
            )

        assert results == []

    def test_min_hits_threshold(self):
        """min_hits 阈值测试：命中小于阈值时被过滤"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import keyword_match_search

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["k1", "k2", "k3"],
            "documents": [
                "退款流程说明",               # 命中 "退款"(1个)
                "退货退款流程详解",             # 命中 "退货"+"退款"(2个)
                "优惠券退款规则",               # 命中 "退款"(1个)
            ],
            "metadatas": [
                {},
                {},
                {},
            ],
        }

        with patch("backend.retrieval.hybrid_search.get_collection", return_value=mock_collection):
            results = keyword_match_search(
                keywords=["退货", "退款"],
                tenant_id="tenant_001",
                kb_types=["faq"],
                min_hits=2,  # 至少命中2个关键词
            )

        # 只有 "退货退款流程详解" 命中2个关键词
        assert len(results) == 1
        assert results[0]["content"] == "退货退款流程详解"
        assert results[0]["_keyword_hits"] == 2

    def test_min_hits_exceeds_keywords_count(self):
        """min_hits 超过关键词数量时，自动限制为关键词数量"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import keyword_match_search

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["k1", "k2"],
            "documents": [
                "退款退货流程",
                "其他内容无关",
            ],
            "metadatas": [
                {},
                {},
            ],
        }

        with patch("backend.retrieval.hybrid_search.get_collection", return_value=mock_collection):
            results = keyword_match_search(
                keywords=["退款"],
                tenant_id="tenant_001",
                kb_types=["faq"],
                min_hits=5,  # 只有1个关键词，实际 min_hits 应为 1
            )

        # min_hits 被限制为 min(5, 1) = 1，所以命中1个即可
        assert len(results) == 1
        assert results[0]["content"] == "退款退货流程"

    def test_empty_keywords(self):
        """空关键词列表 → 返回 []"""
        from backend.retrieval.hybrid_search import keyword_match_search

        results = keyword_match_search(
            keywords=[],
            tenant_id="tenant_001",
        )

        assert results == []

    def test_kb_types_filter(self):
        """限定 kb_types 过滤：只检索指定的知识库类型"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import keyword_match_search

        mock_collection_faq = MagicMock()
        mock_collection_faq.get.return_value = {
            "ids": ["faq_1"],
            "documents": ["FAQ退款说明"],
            "metadatas": [{}],
        }

        mock_collection_product = MagicMock()
        mock_collection_product.get.return_value = {
            "ids": ["product_1"],
            "documents": ["商品退款政策"],
            "metadatas": [{}],
        }

        call_counts = {"faq": 0, "product": 0}

        def get_collection_side_effect(tenant_id, kb_type):
            call_counts[kb_type] = call_counts.get(kb_type, 0) + 1
            if kb_type == "faq":
                return mock_collection_faq
            elif kb_type == "product":
                return mock_collection_product
            return MagicMock()

        with patch("backend.retrieval.hybrid_search.get_collection", side_effect=get_collection_side_effect):
            results = keyword_match_search(
                keywords=["退款"],
                tenant_id="tenant_001",
                kb_types=["faq"],  # 只检索 faq
                min_hits=1,
            )

        # 只调用了 faq 的 collection
        assert call_counts["faq"] == 1
        assert "product" not in call_counts or call_counts["product"] == 0
        assert len(results) == 1
        assert results[0]["kb_type"] == "faq"

    def test_top_k_limit(self):
        """top_k 限制返回数量"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import keyword_match_search

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": [f"k{i}" for i in range(10)],
            "documents": ["退款流程" + str(i) for i in range(10)],
            "metadatas": [{} for _ in range(10)],
        }

        with patch("backend.retrieval.hybrid_search.get_collection", return_value=mock_collection):
            results = keyword_match_search(
                keywords=["退款"],
                tenant_id="tenant_001",
                kb_types=["faq"],
                top_k=3,
                min_hits=1,
            )

        assert len(results) == 3

    def test_where_document_filter_fallback(self):
        """where_document 过滤失败时降级为全量扫描"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import keyword_match_search

        mock_collection = MagicMock()
        # 第一次调用（where_document）抛异常
        # 第二次调用（全量扫描）正常返回
        mock_collection.get.side_effect = [
            Exception("where_document failed"),
            {
                "ids": ["k1", "k2"],
                "documents": ["退款说明", "其他内容"],
                "metadatas": [{}, {}],
            },
        ]

        with patch("backend.retrieval.hybrid_search.get_collection", return_value=mock_collection):
            results = keyword_match_search(
                keywords=["退款"],
                tenant_id="tenant_001",
                kb_types=["faq"],
                min_hits=1,
            )

        # 降级后正常返回匹配结果
        assert len(results) == 1
        assert results[0]["content"] == "退款说明"
        # 验证调用了两次 get
        assert mock_collection.get.call_count == 2

    def test_score_calculation_partial_match(self):
        """部分匹配时 score = hits / len(keywords)"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import keyword_match_search

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["k1"],
            "documents": ["退款流程说明"],
            "metadatas": [{}],
        }

        with patch("backend.retrieval.hybrid_search.get_collection", return_value=mock_collection):
            results = keyword_match_search(
                keywords=["退款", "退货", "优惠券"],
                tenant_id="tenant_001",
                kb_types=["faq"],
                min_hits=1,
            )

        assert len(results) == 1
        # 命中1个关键词 / 3个关键词 = 0.3333
        assert results[0]["score"] == round(1 / 3, 4)

    def test_case_insensitive_match(self):
        """关键词匹配不区分大小写"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import keyword_match_search

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["k1"],
            "documents": ["REFUND POLICY DETAILS"],
            "metadatas": [{}],
        }

        with patch("backend.retrieval.hybrid_search.get_collection", return_value=mock_collection):
            results = keyword_match_search(
                keywords=["refund", "policy"],
                tenant_id="tenant_001",
                kb_types=["faq"],
                min_hits=1,
            )

        assert len(results) == 1
        assert results[0]["_keyword_hits"] == 2


# ==================== _rrf_fuse 测试 ====================

class TestRRFFuse:
    """_rrf_fuse RRF 融合算法测试"""

    def test_vector_only(self):
        """仅有向量结果时，RRF 分数 = vector_weight / (k + rank)"""
        from backend.retrieval.hybrid_search import _rrf_fuse

        vector_results = [
            {"content": "文档A", "score": 0.9, "kb_type": "faq", "source": "manual", "source_id": "a", "metadata": {}},
            {"content": "文档B", "score": 0.7, "kb_type": "faq", "source": "auto", "source_id": "b", "metadata": {}},
        ]

        fused = _rrf_fuse(vector_results, [])

        assert len(fused) == 2
        # 文档A rank=1, rrf = 0.7/(60+1) ≈ 0.011475
        assert fused[0]["content"] == "文档A"
        assert fused[0]["rrf_score"] > fused[1]["rrf_score"]
        assert "vector_score" in fused[0]

    def test_keyword_only(self):
        """仅有关键词结果时，RRF 分数 = keyword_weight / (k + rank)"""
        from backend.retrieval.hybrid_search import _rrf_fuse

        keyword_results = [
            {"content": "关键词文档A", "score": 0.8, "kb_type": "faq", "source": "keyword", "source_id": "ka", "metadata": {}},
        ]

        fused = _rrf_fuse([], keyword_results)

        assert len(fused) == 1
        assert fused[0]["content"] == "关键词文档A"
        assert "keyword_score" in fused[0]

    def test_both_roots_dedup(self):
        """两路都有结果，相同文档去重并累加 RRF 分数"""
        from backend.retrieval.hybrid_search import _rrf_fuse

        vector_results = [
            {"content": "共享文档", "score": 0.9, "kb_type": "faq", "source": "manual", "source_id": "shared", "metadata": {}},
            {"content": "仅向量文档", "score": 0.6, "kb_type": "faq", "source": "auto", "source_id": "vec_only", "metadata": {}},
        ]
        keyword_results = [
            {"content": "共享文档", "score": 0.8, "kb_type": "faq", "source": "keyword", "source_id": "shared", "metadata": {}},
            {"content": "仅关键词文档", "score": 0.5, "kb_type": "faq", "source": "keyword", "source_id": "kw_only", "metadata": {}},
        ]

        fused = _rrf_fuse(vector_results, keyword_results)

        # 3 个唯一文档（共享文档去重）
        assert len(fused) == 3
        # 共享文档在两路都被召回，RRF 分数最高
        assert fused[0]["content"] == "共享文档"
        assert fused[0]["rrf_score"] > 0
        # 共享文档同时有 vector_score 和 keyword_score
        assert "vector_score" in fused[0]
        assert "keyword_score" in fused[0]

    def test_rrf_score_calculation(self):
        """验证 RRF 分数计算正确性"""
        from backend.retrieval.hybrid_search import _rrf_fuse

        vector_results = [
            {"content": "文档1", "score": 0.9, "kb_type": "faq", "source": "manual", "source_id": "1", "metadata": {}},
        ]
        keyword_results = [
            {"content": "文档1", "score": 0.8, "kb_type": "faq", "source": "keyword", "source_id": "1", "metadata": {}},
        ]

        fused = _rrf_fuse(vector_results, keyword_results, rrf_k=60, vector_weight=0.7, keyword_weight=0.3)

        assert len(fused) == 1
        # 文档1 向量路 rank=1: 0.7/(60+1) = 0.7/61 ≈ 0.011475
        # 文档1 关键词路 rank=1: 0.3/(60+1) = 0.3/61 ≈ 0.004918
        # 总计 ≈ 0.016393
        expected = round(0.7 / 61 + 0.3 / 61, 6)
        assert fused[0]["rrf_score"] == expected

    def test_empty_both(self):
        """两路都为空 → 返回 []"""
        from backend.retrieval.hybrid_search import _rrf_fuse

        fused = _rrf_fuse([], [])
        assert fused == []

    def test_keyword_hits_cleaned(self):
        """融合后 _keyword_hits 内部字段被清理"""
        from backend.retrieval.hybrid_search import _rrf_fuse

        keyword_results = [
            {"content": "文档A", "score": 0.8, "kb_type": "faq", "source": "keyword", "source_id": "a", "metadata": {}, "_keyword_hits": 3},
        ]

        fused = _rrf_fuse([], keyword_results)
        assert "_keyword_hits" not in fused[0]

    def test_fused_score_equals_rrf_score(self):
        """融合后 score 字段等于 rrf_score"""
        from backend.retrieval.hybrid_search import _rrf_fuse

        vector_results = [
            {"content": "文档A", "score": 0.9, "kb_type": "faq", "source": "manual", "source_id": "a", "metadata": {}},
        ]

        fused = _rrf_fuse(vector_results, [])
        assert fused[0]["score"] == fused[0]["rrf_score"]


# ==================== hybrid_search 测试 ====================

class TestHybridSearch:
    """hybrid_search 函数测试（mock embed_query_cached + query_collection）"""

    def test_normal_hybrid_search(self):
        """正常混合检索"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        mock_raw_result = {
            "ids": [["doc_a", "doc_b"]],
            "documents": [["文档A内容", "文档B内容"]],
            "metadatas": [
                [
                    {"kb_type": "faq", "source_type": "manual"},
                    {"kb_type": "faq", "source_type": "auto"},
                ]
            ],
            "distances": [[0.2, 0.5]],
        }

        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", return_value=mock_raw_result):
            results = hybrid_search(
                query="如何退款",
                tenant_id="tenant_001",
                kb_types=["faq"],
            )

        assert len(results) == 2
        assert results[0]["content"] == "文档A内容"
        assert results[0]["score"] == round(1.0 - 0.2, 4)
        assert results[0]["kb_type"] == "faq"
        assert results[1]["content"] == "文档B内容"

    def test_empty_result(self):
        """空结果 → 返回 []"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        mock_raw_result = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", return_value=mock_raw_result):
            results = hybrid_search(
                query="测试查询",
                tenant_id="tenant_001",
                kb_types=["faq"],
            )

        assert results == []

    def test_relevance_threshold_filter(self):
        """相关性阈值过滤：低于阈值的文档被排除"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        # distances: 0.1→similarity=0.9, 0.4→similarity=0.6, 0.85→similarity=0.15
        mock_raw_result = {
            "ids": [["high_rel", "mid_rel", "low_rel"]],
            "documents": [["高相关", "中相关", "低相关"]],
            "metadatas": [
                [
                    {"kb_type": "faq"},
                    {"kb_type": "faq"},
                    {"kb_type": "faq"},
                ]
            ],
            "distances": [[0.1, 0.4, 0.85]],
        }

        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", return_value=mock_raw_result):
            results = hybrid_search(
                query="测试查询",
                tenant_id="tenant_001",
                kb_types=["faq"],
                relevance_threshold=0.5,  # 只保留 similarity >= 0.5
            )

        assert len(results) == 2
        assert results[0]["score"] == round(1.0 - 0.1, 4)  # 0.9
        assert results[1]["score"] == round(1.0 - 0.4, 4)  # 0.6
        # low_rel (0.15) 被过滤掉了

    def test_default_relevance_threshold(self):
        """默认相关性阈值（从 RETRIEVAL_THRESHOLD 配置读取）"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        # similarity = 1.0 - 0.25 = 0.75 > 默认阈值 0.2，应保留
        mock_raw_result = {
            "ids": [["doc1"]],
            "documents": [["匹配内容"]],
            "metadatas": [[{"kb_type": "faq"}]],
            "distances": [[0.25]],
        }

        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", return_value=mock_raw_result):
            results = hybrid_search(
                query="测试",
                tenant_id="tenant_001",
                kb_types=["faq"],
            )

        assert len(results) == 1

    def test_score_sorting(self):
        """验证结果按 score 降序排列"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        mock_raw_result = {
            "ids": [["C", "A", "B"]],
            "documents": [["第三", "第一", "第二"]],
            "metadatas": [
                [
                    {"kb_type": "faq"},
                    {"kb_type": "faq"},
                    {"kb_type": "faq"},
                ]
            ],
            "distances": [[0.7, 0.1, 0.4]],  # similarity: 0.3, 0.9, 0.6
        }

        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", return_value=mock_raw_result):
            results = hybrid_search(
                query="测试",
                tenant_id="tenant_001",
                kb_types=["faq"],
                relevance_threshold=0.0,
            )

        assert len(results) == 3
        assert results[0]["score"] == 0.9
        assert results[1]["score"] == 0.6
        assert results[2]["score"] == 0.3

    def test_top_k_limit(self):
        """验证 top_k 限制返回数量"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        mock_raw_result = {
            "ids": [[f"doc{i}" for i in range(10)]],
            "documents": [[f"内容{i}" for i in range(10)]],
            "metadatas": [[{"kb_type": "faq"} for _ in range(10)]],
            "distances": [[0.1 + i * 0.05 for i in range(10)]],
        }

        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", return_value=mock_raw_result):
            results = hybrid_search(
                query="测试",
                tenant_id="tenant_001",
                kb_types=["faq"],
                top_k=4,
                relevance_threshold=0.0,
            )

        assert len(results) == 4

    def test_query_collection_failure_graceful(self):
        """query_collection 失败时优雅处理，不阻塞其他 collection"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        # faq 返回正常结果，product 抛异常
        mock_faq_result = {
            "ids": [["faq_doc"]],
            "documents": [["FAQ文档"]],
            "metadatas": [[{"kb_type": "faq"}]],
            "distances": [[0.2]],
        }

        def query_side_effect(tenant_id, kb_type, query_embeddings, n_results):
            if kb_type == "product":
                raise Exception("collection not found")
            return mock_faq_result

        # 使用单 kb_type 顺序执行路径（len(kb_types) == 1），跳过线程池并行
        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", side_effect=query_side_effect):
            results = hybrid_search(
                query="测试",
                tenant_id="tenant_001",
                kb_types=["faq"],
            )

        assert len(results) == 1
        assert results[0]["kb_type"] == "faq"

    def test_hybrid_with_keywords_fusion(self):
        """传入 keywords 时，向量路 + 关键词路双路融合"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        mock_raw_result = {
            "ids": [["doc_a", "doc_b"]],
            "documents": [["退货退款流程说明", "商品尺寸对照表"]],
            "metadatas": [
                [
                    {"kb_type": "faq", "source_type": "manual"},
                    {"kb_type": "faq", "source_type": "auto"},
                ]
            ],
            "distances": [[0.2, 0.5]],
        }

        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["k1"],
            "documents": ["退货退款流程说明"],
            "metadatas": [{"source_type": "keyword"}],
        }

        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", return_value=mock_raw_result), \
             patch("backend.retrieval.hybrid_search.get_collection", return_value=mock_collection):
            results = hybrid_search(
                query="如何退货",
                tenant_id="tenant_001",
                kb_types=["faq"],
                keywords=["退货", "退款"],
            )

        # 应有融合结果
        assert len(results) >= 1
        # "退货退款流程说明" 在两路都被召回，RRF 分数应最高
        assert results[0]["content"] == "退货退款流程说明"
        assert "rrf_score" in results[0]

    def test_hybrid_without_keywords_vector_only(self):
        """不传 keywords 时，仅走向量路，不调用 keyword_match_search"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        mock_raw_result = {
            "ids": [["doc_a"]],
            "documents": [["向量结果"]],
            "metadatas": [[{"kb_type": "faq"}]],
            "distances": [[0.2]],
        }

        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", return_value=mock_raw_result), \
             patch("backend.retrieval.hybrid_search.keyword_match_search") as mock_kw:
            results = hybrid_search(
                query="测试",
                tenant_id="tenant_001",
                kb_types=["faq"],
                keywords=None,  # 不传关键词
            )

        # keyword_match_search 不应被调用
        mock_kw.assert_not_called()
        assert len(results) == 1
        assert results[0]["content"] == "向量结果"

    def test_keyword_search_failure_fallback_to_vector(self):
        """关键词检索失败时，降级为纯向量结果"""
        from unittest.mock import MagicMock, patch
        from backend.retrieval.hybrid_search import hybrid_search

        mock_embedding = [0.1, 0.2, 0.3]

        mock_raw_result = {
            "ids": [["doc_a"]],
            "documents": [["向量降级结果"]],
            "metadatas": [[{"kb_type": "faq"}]],
            "distances": [[0.2]],
        }

        with patch("backend.retrieval.hybrid_search.embed_query_cached", return_value=mock_embedding), \
             patch("backend.retrieval.hybrid_search.query_collection", return_value=mock_raw_result), \
             patch("backend.retrieval.hybrid_search.keyword_match_search", side_effect=Exception("keyword error")):
            results = hybrid_search(
                query="测试",
                tenant_id="tenant_001",
                kb_types=["faq"],
                keywords=["测试关键词"],
            )

        # 降级为向量结果
        assert len(results) == 1
        assert results[0]["content"] == "向量降级结果"


# ==================== 运行入口 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])