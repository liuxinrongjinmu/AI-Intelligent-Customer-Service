"""
同步服务：实时处理知识库同步操作

设计说明：
  聚宝赞端将单次批量操作控制在 10 条左右，因此同步处理采用实时模式，
  直接在 API 请求线程中完成 embedding + 写入，不再使用异步 task_id + 轮询。

核心函数：
  process_sync()  全量/增量同步（实时）
  process_batch() 批量增删（实时）
"""
import logging
import os
import time

from backend.retrieval.vector_store import (
    clear_collection, add_to_collection_sync, delete_from_collection
)
from backend.retrieval.embedding import get_embedding_model
from backend.retrieval.chunker import chunk_items

logger = logging.getLogger(__name__)

# 批量 embedding 大小，可通过环境变量 SYNC_BATCH_EMBED_SIZE 配置
BATCH_EMBED_SIZE = int(os.getenv("SYNC_BATCH_EMBED_SIZE", "32"))


def process_sync(
    tenant_id: str,
    kb_type: str,
    sync_type: str,
    items: list[dict],
    full_replace: bool = False,
) -> dict:
    """
    实时处理全量/增量同步

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型
    :param sync_type: 同步类型（full / incremental）
    :param items: 知识条目列表 [{id, content, metadata}, ...]
    :param full_replace: 是否先清空再写入
    :return: {"processed_count": int, "deleted_count": int}
    """
    total = len(items) if items else 0
    logger.info(
        f"同步处理开始: tenant={tenant_id}, kb_type={kb_type}, "
        f"sync_type={sync_type}, total={total}"
    )

    deleted = 0

    # 全量替换 → 先清空 collection
    if full_replace:
        clear_collection(tenant_id, kb_type)
        logger.info(f"同步清空 collection: tenant={tenant_id}, kb_type={kb_type}")

    if not items:
        return {"processed_count": 0, "deleted_count": deleted}

    # chunk 处理后写入
    items = chunk_items(items)
    total = len(items)

    embedding_model = get_embedding_model()
    processed = 0

    # Phase 1: 收集所有 content，批量计算 embedding
    contents = [item.get("content", "") for item in items]

    t0 = time.time()
    all_embeddings = []
    for i in range(0, len(contents), BATCH_EMBED_SIZE):
        batch = contents[i:i + BATCH_EMBED_SIZE]
        embeddings = embedding_model.embed_documents(batch)
        all_embeddings.extend(embeddings)
    embed_time = time.time() - t0
    logger.info(f"批量 embedding 完成: count={len(all_embeddings)}, time={embed_time:.2f}s")

    # Phase 2: 逐条写入 ChromaDB
    for idx, item in enumerate(items):
        item_id = item.get("id", "")
        content = contents[idx]
        meta = dict(item.get("metadata", {})) if item.get("metadata") else {}
        meta["kb_type"] = kb_type
        meta["source_id"] = item_id

        try:
            t1 = time.time()
            add_to_collection_sync(
                tenant_id=tenant_id,
                kb_type=kb_type,
                ids=[item_id],
                documents=[content],
                metadatas=[meta],
                embeddings=[all_embeddings[idx]]
            )
            write_time = time.time() - t1
            processed += 1

            logger.debug(
                f"同步进度: {processed}/{total}, "
                f"write={write_time:.2f}s"
            )
        except Exception as e:
            logger.error(f"同步处理单条失败: id={item_id}, error={e}")

    logger.info(
        f"同步处理完成: tenant={tenant_id}, kb_type={kb_type}, "
        f"processed={processed}, deleted={deleted}"
    )

    return {"processed_count": processed, "deleted_count": deleted}


def process_batch(
    tenant_id: str,
    kb_type: str,
    items: list[dict],
    delete_ids: list[str] | None = None,
) -> dict:
    """
    实时处理批量增删

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型
    :param items: 新增/更新的知识条目
    :param delete_ids: 需要删除的文档ID列表
    :return: {"processed_count": int, "deleted_count": int}
    """
    logger.info(
        f"批量操作开始: tenant={tenant_id}, kb_type={kb_type}, "
        f"add={len(items) if items else 0}, delete={len(delete_ids) if delete_ids else 0}"
    )

    # Phase 1: 处理删除
    deleted = 0
    if delete_ids:
        delete_from_collection(tenant_id, kb_type, delete_ids)
        deleted = len(delete_ids)
        logger.info(f"批量删除完成: tenant={tenant_id}, deleted={deleted}")

    # Phase 2: 处理新增/更新
    if not items:
        return {"processed_count": 0, "deleted_count": deleted}

    items = chunk_items(items)
    total = len(items)

    embedding_model = get_embedding_model()
    processed = 0

    # Phase 2a: 收集所有 content，批量计算 embedding
    contents = [item.get("content", "") for item in items]

    all_embeddings = []
    for i in range(0, len(contents), BATCH_EMBED_SIZE):
        batch = contents[i:i + BATCH_EMBED_SIZE]
        embeddings = embedding_model.embed_documents(batch)
        all_embeddings.extend(embeddings)

    # Phase 2b: 逐条写入 ChromaDB
    for idx, item in enumerate(items):
        item_id = item.get("id", "")
        content = contents[idx]
        meta = dict(item.get("metadata", {})) if item.get("metadata") else {}
        meta["kb_type"] = kb_type
        meta["source_id"] = item_id

        try:
            add_to_collection_sync(
                tenant_id=tenant_id,
                kb_type=kb_type,
                ids=[item_id],
                documents=[content],
                metadatas=[meta],
                embeddings=[all_embeddings[idx]]
            )
            processed += 1
        except Exception as e:
            logger.error(f"批量处理单条失败: id={item_id}, error={e}")

    logger.info(
        f"批量操作完成: tenant={tenant_id}, kb_type={kb_type}, "
        f"processed={processed}, deleted={deleted}"
    )

    return {"processed_count": processed, "deleted_count": deleted}