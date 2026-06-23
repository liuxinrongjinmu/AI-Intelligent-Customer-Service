"""
FAQ 知识库服务：FAQ增删改查 + ChromaDB向量化同步

优化：批量 embed + 批量 commit，消除 N+1 问题
"""
import logging
from sqlalchemy.orm import Session
from backend.models.knowledge import FAQ, Document
from backend.retrieval.embedding import get_embedding_model
from backend.retrieval.vector_store import (
    add_to_collection_sync,
    delete_from_collection,
    get_collection,
)

logger = logging.getLogger(__name__)

# 批量 embed 的批次大小
_BATCH_EMBED_SIZE = 100


def sync_faq_to_chromadb(db: Session, faq: FAQ):
    """
    将单条 FAQ 同步到 ChromaDB
    """
    tenant_id = faq.tenant_id
    embedding_model = get_embedding_model()

    content = f"Q: {faq.question}\nA: {faq.answer}"
    embedding = embedding_model.embed_documents([content])

    chroma_id = f"faq-{faq.id}"
    metadata = {
        "tenant_id": tenant_id,
        "source_type": "faq",
        "source_id": str(faq.id),
        "category": faq.category,
        "tags": faq.tags,
        "question": faq.question,
    }

    add_to_collection_sync(
        tenant_id=tenant_id,
        kb_type="faq",
        ids=[chroma_id],
        documents=[content],
        metadatas=[metadata],
        embeddings=embedding,
    )

    faq.chroma_ids = chroma_id
    db.commit()
    logger.info(f"FAQ #{faq.id} 已同步到 ChromaDB")


def remove_faq_from_chromadb(faq: FAQ):
    """
    从 ChromaDB 删除 FAQ 向量
    """
    if faq.chroma_ids:
        ids = faq.chroma_ids.split(",")
        delete_from_collection(faq.tenant_id, "faq", ids)
        logger.info(f"FAQ #{faq.id} 已从 ChromaDB 删除")


def create_faq(db: Session, tenant_id: str, question: str, answer: str,
               category: str = "通用", tags: str = "") -> FAQ:
    """
    创建FAQ并同步向量化

    :param db: 数据库会话
    :param tenant_id: 租户 ID
    :param question: 问题
    :param answer: 答案
    :param category: 分类
    :param tags: 标签
    :return: FAQ 对象
    """
    faq = FAQ(
        tenant_id=tenant_id,
        question=question,
        answer=answer,
        category=category,
        tags=tags,
    )
    db.add(faq)
    db.commit()
    db.refresh(faq)

    try:
        sync_faq_to_chromadb(db, faq)
    except Exception as e:
        # 向量库同步失败，回滚 DB 以保持数据一致性
        logger.error(f"FAQ #{faq.id} ChromaDB同步失败，回滚DB: {e}")
        db.delete(faq)
        db.commit()
        raise RuntimeError(f"FAQ创建失败：向量库同步异常 - {e}")

    return faq


def update_faq(db: Session, faq: FAQ, **kwargs) -> FAQ:
    """
    更新FAQ并重新同步向量
    """
    for key, value in kwargs.items():
        if value is not None and hasattr(faq, key):
            setattr(faq, key, value)

    db.commit()
    db.refresh(faq)

    try:
        if faq.chroma_ids:
            remove_faq_from_chromadb(faq)
        sync_faq_to_chromadb(db, faq)
    except Exception as e:
        logger.error(f"FAQ #{faq.id} ChromaDB更新同步失败: {e}")

    return faq


def delete_faq(db: Session, faq: FAQ):
    """
    删除FAQ及对应向量
    """
    try:
        remove_faq_from_chromadb(faq)
    except Exception as e:
        logger.error(f"FAQ #{faq.id} ChromaDB删除失败: {e}")

    db.delete(faq)
    db.commit()


def sync_all_faqs_for_tenant(db: Session, tenant_id: str):
    """
    全量同步某个租户的所有FAQ到ChromaDB（用于首次初始化）

    优化：批量 embed + 批量写入 ChromaDB，消除 N+1 问题
    """
    faqs = db.query(FAQ).filter_by(tenant_id=tenant_id, is_enabled=True).all()
    unsynced = [f for f in faqs if not f.chroma_ids]

    if not unsynced:
        logger.info(f"租户 {tenant_id} 无需同步，所有 FAQ 已在 ChromaDB 中")
        return

    embedding_model = get_embedding_model()
    total = len(unsynced)
    logger.info(f"租户 {tenant_id} 开始批量同步 {total} 条 FAQ")

    # 分批 embed + 写入
    for batch_start in range(0, total, _BATCH_EMBED_SIZE):
        batch = unsynced[batch_start:batch_start + _BATCH_EMBED_SIZE]

        ids = []
        documents = []
        metadatas = []

        for faq in batch:
            chroma_id = f"faq-{faq.id}"
            content = f"Q: {faq.question}\nA: {faq.answer}"
            ids.append(chroma_id)
            documents.append(content)
            metadatas.append({
                "tenant_id": tenant_id,
                "source_type": "faq",
                "source_id": str(faq.id),
                "category": faq.category,
                "tags": faq.tags,
                "question": faq.question,
            })

        # 批量 embed
        embeddings = embedding_model.embed_documents(documents)

        # 批量写入 ChromaDB
        add_to_collection_sync(
            tenant_id=tenant_id,
            kb_type="faq",
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        # 批量更新 chroma_ids
        for faq in batch:
            faq.chroma_ids = f"faq-{faq.id}"
        db.commit()

        logger.info(f"租户 {tenant_id} FAQ 同步进度: {batch_start + len(batch)}/{total}")

    logger.info(f"租户 {tenant_id} 全量同步完成，共 {total} 条FAQ")


def sync_document_to_chromadb(db: Session, doc_record: Document, chunks: list, tenant_id: str, kb_type: str = "rule"):
    """
    将文档切片同步到 ChromaDB

    :param db: 数据库会话
    :param doc_record: 文档记录
    :param chunks: 文档切片列表
    :param tenant_id: 租户ID
    :param kb_type: 知识库类型（默认 rule，避免与 FAQ 混在同一 collection）
    """
    embedding_model = get_embedding_model()

    ids = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):
        chroma_id = f"doc-{doc_record.id}-chunk-{i}"
        ids.append(chroma_id)

        chunk_text = chunk.page_content if hasattr(chunk, 'page_content') else str(chunk)
        documents.append(chunk_text)

        metadatas.append({
            "tenant_id": tenant_id,
            "source_type": "document",
            "source_id": str(doc_record.id),
            "filename": doc_record.filename,
            "chunk_index": i,
            "total_chunks": len(chunks),
        })

    embeddings_list = embedding_model.embed_documents(documents)

    add_to_collection_sync(
        tenant_id=tenant_id,
        kb_type=kb_type,
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings_list,
    )

    doc_record.chroma_ids = ",".join(ids)
    doc_record.chunk_count = len(chunks)
    db.commit()
    logger.info(f"文档 #{doc_record.id} 已同步到 ChromaDB ({kb_type})，{len(chunks)} 个切片")


def remove_document_from_chromadb(doc_record: Document, kb_type: str = "rule"):
    """
    从 ChromaDB 删除文档所有切片

    :param doc_record: 文档记录
    :param kb_type: 知识库类型（需与写入时一致）
    """
    if doc_record.chroma_ids:
        ids = doc_record.chroma_ids.split(",")
        delete_from_collection(doc_record.tenant_id, kb_type, ids)
        logger.info(f"文档 #{doc_record.id} 已从 ChromaDB ({kb_type}) 删除")
