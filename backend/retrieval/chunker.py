"""
文档分块工具：滑动窗口分块

仅对超过 chunk_size 的长文档进行分块，短文档保持不变。
分块时保留原始文档 ID，通过后缀 _chunk_N 区分。
"""
from backend.config import DOC_CHUNK_SIZE, DOC_CHUNK_OVERLAP


def chunk_document(doc_id: str, content: str, metadata: dict | None = None,
                   chunk_size: int = DOC_CHUNK_SIZE,
                   chunk_overlap: int = DOC_CHUNK_OVERLAP) -> list[dict]:
    """
    对单个文档进行滑动窗口分块
    
    :param doc_id: 原始文档 ID
    :param content: 文档内容
    :param metadata: 元数据
    :param chunk_size: 每块最大字符数
    :param chunk_overlap: 相邻块重叠字符数
    :return: 分块列表 [{id, content, metadata}, ...]，短文档返回原始文档
    """
    if not content or len(content) <= chunk_size:
        return [{
            "id": doc_id,
            "content": content,
            "metadata": metadata or {},
        }]

    chunks = []
    start = 0
    chunk_idx = 0

    while start < len(content):
        end = start + chunk_size
        chunk_text = content[start:end]
        chunk_id = f"{doc_id}_chunk_{chunk_idx}"
        chunk_meta = dict(metadata or {})
        chunk_meta["chunk_index"] = chunk_idx
        chunk_meta["original_id"] = doc_id

        chunks.append({
            "id": chunk_id,
            "content": chunk_text,
            "metadata": chunk_meta,
        })

        start = end - chunk_overlap
        chunk_idx += 1

        if start >= len(content):
            break

    return chunks


def chunk_items(items: list[dict], chunk_size: int = DOC_CHUNK_SIZE,
                 chunk_overlap: int = DOC_CHUNK_OVERLAP) -> list[dict]:
    """
    对一批知识条目进行分块处理
    
    :param items: 原始知识条目列表 [{id, content, metadata}, ...]
    :param chunk_size: 每块最大字符数
    :param chunk_overlap: 相邻块重叠字符数
    :return: 分块后的条目列表
    """
    result = []
    for item in items:
        chunks = chunk_document(
            doc_id=item.get("id", ""),
            content=item.get("content", ""),
            metadata=item.get("metadata"),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        result.extend(chunks)
    return result