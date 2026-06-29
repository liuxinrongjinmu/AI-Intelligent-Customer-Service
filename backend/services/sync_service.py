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
from typing import Optional

from backend.retrieval.vector_store import (
    clear_collection, add_to_collection_sync, delete_from_collection, get_collection
)
from backend.retrieval.embedding import embed_documents_async
from backend.retrieval.chunker import chunk_items

logger = logging.getLogger(__name__)

# 批量 embedding 大小，可通过环境变量 SYNC_BATCH_EMBED_SIZE 配置
BATCH_EMBED_SIZE = int(os.getenv("SYNC_BATCH_EMBED_SIZE", "32"))


async def process_sync(
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
    failed = 0

    # 原子化全量替换：先写入新数据，全部成功后再删除旧数据
    # 避免写入中途失败导致知识库进入空状态
    old_ids_to_delete: set[str] = set()
    if full_replace:
        try:
            collection = get_collection(tenant_id, kb_type)
            existing = collection.get()
            if existing and existing.get("ids"):
                old_ids_to_delete = set(existing["ids"])
        except Exception as e:
            logger.warning(f"获取已有文档ID失败，降级为先清空再写入: {e}")
            clear_collection(tenant_id, kb_type)
            logger.info(f"同步清空 collection（降级）: tenant={tenant_id}, kb_type={kb_type}")

    if not items:
        return {"processed_count": 0, "deleted_count": deleted}

    # 保存原始 items 引用用于快照（chunk_items 会修改 ID）
    _original_items = items
    # chunk 处理后写入
    items = chunk_items(items)
    total = len(items)

    processed = 0

    # Phase 1: 收集所有 content，批量计算 embedding（异步，不阻塞事件循环）
    contents = [item.get("content", "") for item in items]

    t0 = time.time()
    all_embeddings = []
    for i in range(0, len(contents), BATCH_EMBED_SIZE):
        batch = contents[i:i + BATCH_EMBED_SIZE]
        embeddings = await embed_documents_async(batch)
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
            failed += 1

    # 同步状态：全部成功为 success，部分失败为 partial
    sync_status = "success" if failed == 0 else "partial"

    # 原子化全量替换：写入完成后，删除不在新数据集中的旧文档
    if full_replace and old_ids_to_delete:
        new_ids = {item.get("id", "") for item in items}
        ids_to_remove = old_ids_to_delete - new_ids
        if ids_to_remove:
            try:
                delete_from_collection(tenant_id, kb_type, list(ids_to_remove), async_write=False)
                deleted = len(ids_to_remove)
                logger.info(f"原子替换删除旧文档: tenant={tenant_id}, kb_type={kb_type}, deleted={deleted}")
            except Exception as e:
                logger.error(f"删除旧文档失败（新数据已写入，旧数据残留）: {e}")

    logger.info(
        f"同步处理完成: tenant={tenant_id}, kb_type={kb_type}, "
        f"processed={processed}, deleted={deleted}, failed={failed}, status={sync_status}"
    )

    # 记录同步日志（含快照，用于回滚）
    # 回滚操作本身不记录 sync_log，避免污染回滚源
    # （否则下次 get_last_sync_snapshot 会取到回滚自身的快照，而非原始同步）
    if sync_type != "rollback":
        from backend.knowledge.sync_log import record_sync_log
        from backend.config import MAX_SYNC_BATCH_SIZE
        if len(items) > MAX_SYNC_BATCH_SIZE:
            logger.warning(f"快照截断: items={len(items)}, 仅保留前 {MAX_SYNC_BATCH_SIZE} 条，回滚可能不完整")
        snapshot = [_build_snapshot_item(item) for item in _original_items[:MAX_SYNC_BATCH_SIZE]]
        record_sync_log(
            tenant_id=tenant_id,
            kb_type=kb_type,
            sync_type=sync_type,
            item_count=total,
            processed_count=processed,
            deleted_count=deleted,
            status=sync_status,
            snapshot=snapshot,
        )

    # 同步写入关系型 FAQ/Document 表（便于管理后台查询）
    _persist_relational_records(tenant_id, kb_type, items, full_replace)

    return {"processed_count": processed, "deleted_count": deleted}


async def process_batch(
    tenant_id: str,
    kb_type: str,
    items: list[dict],
    delete_ids: Optional[list[str]] = None,
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

    _original_items = items
    items = chunk_items(items)
    total = len(items)

    processed = 0

    # Phase 2a: 收集所有 content，批量计算 embedding（异步）
    contents = [item.get("content", "") for item in items]

    all_embeddings = []
    for i in range(0, len(contents), BATCH_EMBED_SIZE):
        batch = contents[i:i + BATCH_EMBED_SIZE]
        embeddings = await embed_documents_async(batch)
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

    # 记录同步日志（含快照，用于回滚）
    from backend.knowledge.sync_log import record_sync_log
    snapshot = [_build_snapshot_item(item) for item in _original_items[:MAX_SYNC_BATCH_SIZE]]
    record_sync_log(
        tenant_id=tenant_id,
        kb_type=kb_type,
        sync_type="batch",
        item_count=total,
        processed_count=processed,
        deleted_count=deleted,
        status="success",
        snapshot=snapshot,
    )

    # 同步写入关系型 FAQ/Document 表（增量模式）
    _persist_relational_records(tenant_id, kb_type, items, full_replace=False)

    return {"processed_count": processed, "deleted_count": deleted}


# ============================================================
# 辅助函数
# ============================================================

def _build_snapshot_item(item: dict) -> dict:
    """
    构建同步快照条目（精简字段，用于回滚）

    :param item: 原始知识条目
    :return: {id, content, metadata}
    """
    meta = item.get("metadata")
    return {
        "id": item.get("id", ""),
        "content": item.get("content", ""),
        "metadata": meta if isinstance(meta, dict) else {},
    }


def _safe_int(value, default: int) -> int:
    """
    安全转 int，防御 None / 非数字字符串

    :param value: 原始值
    :param default: 转换失败时的默认值
    :return: int 值
    """
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        logger.warning(f"int 转换失败: value={value!r}, 使用默认值={default}")
        return default


def _persist_relational_records(
    tenant_id: str,
    kb_type: str,
    items: list[dict],
    full_replace: bool,
) -> None:
    """
    将知识条目同步写入关系型 FAQ/Document 表

    仅对 faq / document 类型生效，其他类型跳过。
    写入失败不影响主流程，仅记录警告。

    :param tenant_id: 租户ID
    :param kb_type: 知识库类型
    :param items: 知识条目列表
    :param full_replace: 是否全量替换（先删除旧记录）
    """
    if kb_type not in ("faq", "document"):
        return

    try:
        from backend.database import SessionLocal
        from backend.models.knowledge import FAQ, Document

        db = SessionLocal()
        try:
            # DELETE 与 INSERT 在同一事务内，避免中途失败导致数据丢失
            if full_replace:
                if kb_type == "faq":
                    db.query(FAQ).filter(FAQ.tenant_id == tenant_id).delete()
                else:
                    db.query(Document).filter(Document.tenant_id == tenant_id).delete()
                # 不在此处 commit，与后续 INSERT 共享同一事务

            for item in items:
                item_id = item.get("id", "")
                content = item.get("content", "")
                meta = item.get("metadata")
                if not isinstance(meta, dict):
                    meta = {}

                if kb_type == "faq":
                    # FAQ: content 格式约定为 "Q: 问题\nA: 答案" 或纯问题
                    question, answer = _parse_faq_content(content, meta)
                    record = FAQ(
                        tenant_id=tenant_id,
                        question=question,
                        answer=answer,
                        category=meta.get("category", "通用"),
                        tags=meta.get("tags", ""),
                        is_enabled=True,
                        chroma_ids=item_id,
                    )
                    db.add(record)
                else:
                    # Document
                    record = Document(
                        tenant_id=tenant_id,
                        filename=meta.get("filename", item_id),
                        file_type=meta.get("file_type", "txt"),
                        file_size=_safe_int(meta.get("file_size"), len(content)),
                        chunk_count=_safe_int(meta.get("chunk_count"), 1),
                        is_enabled=True,
                        chroma_ids=item_id,
                    )
                    db.add(record)

            db.commit()
            logger.info(
                f"关系表写入完成: tenant={tenant_id}, kb_type={kb_type}, "
                f"count={len(items)}, full_replace={full_replace}"
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"关系表写入失败（不影响向量库）: tenant={tenant_id}, kb_type={kb_type}, error={e}")


def _parse_faq_content(content: str, meta: dict) -> tuple[str, str]:
    """
    解析 FAQ 内容为 (question, answer)

    支持格式：
    - "Q: 问题\nA: 答案"
    - "问题\n答案"
    - metadata 中直接提供 question/answer

    :param content: 原始内容
    :param meta: 元数据
    :return: (question, answer)
    """
    if meta.get("question") and meta.get("answer"):
        return str(meta["question"]), str(meta["answer"])

    if "Q:" in content and "A:" in content:
        parts = content.split("A:", 1)
        question = parts[0].replace("Q:", "").strip()
        answer = parts[1].strip() if len(parts) > 1 else ""
        return question, answer

    lines = content.split("\n", 1)
    question = lines[0].strip()
    answer = lines[1].strip() if len(lines) > 1 else ""
    return question, answer