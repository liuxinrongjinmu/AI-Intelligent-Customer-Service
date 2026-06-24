"""
种子数据初始化：创建演示租户和示例FAQ，并同步到 ChromaDB 向量库
运行方式：python -m backend.seed
"""
import logging
from backend.database import init_db, SessionLocal
from backend.models.tenant import Tenant, generate_api_key
from backend.models.knowledge import FAQ
from backend.retrieval.vector_store import clear_collection, add_to_collection_sync
from backend.retrieval.embedding import get_embedding_model

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


DEMO_FAQS = [
    {
        "question": "退货政策是什么？",
        "answer": "我们支持7天无理由退货。商品需保持完好，不影响二次销售。退回运费由用户承担，质量问题由商家承担。退款将在收到退货后3个工作日内原路返回。",
        "category": "售后",
        "tags": "退货,退款,售后政策"
    },
    {
        "question": "发货时效是多久？",
        "answer": "订单支付成功后，我们会在24小时内发货。如遇大促活动，发货时效可能延长至48小时，请以订单详情页显示的预计发货时间为准。",
        "category": "物流",
        "tags": "发货,时效,物流"
    },
    {
        "question": "如何查询物流信息？",
        "answer": "您可以在订单详情页查看物流轨迹。发货后系统会自动推送物流单号到您的消息中心。也可以联系在线客服提供订单号帮您查询。",
        "category": "物流",
        "tags": "物流,快递,查询"
    },
    {
        "question": "商品有质量问题怎么办？",
        "answer": "如收到商品存在质量问题，请在签收后48小时内联系客服，提供商品照片和问题描述。确认质量问题后，我们将为您办理换货或退货退款，运费由商家承担。",
        "category": "售后",
        "tags": "质量问题,换货,退货"
    },
    {
        "question": "如何修改订单地址？",
        "answer": "订单未发货前，您可以在订单详情页修改收货地址。若订单已发货，请联系客服协助处理，我们将尽力为您联系快递公司修改地址，但不保证一定能成功。",
        "category": "订单",
        "tags": "修改地址,订单,收货地址"
    },
    {
        "question": "优惠券如何使用？",
        "answer": "下单时在结算页面选择可用优惠券即可抵扣。每个订单仅可使用一张优惠券，优惠券不可叠加使用。请注意查看优惠券的使用条件和有效期。",
        "category": "支付",
        "tags": "优惠券,折扣,使用"
    },
    {
        "question": "会员权益有哪些？",
        "answer": "会员享有专属折扣价、生日礼包、优先发货、专属客服等权益。不同等级会员权益不同：普通会员享9.8折，黄金会员享9.5折，铂金会员享9折并享优先发货。",
        "category": "会员",
        "tags": "会员,权益,等级,折扣"
    },
    {
        "question": "如何联系人工客服？",
        "answer": "如果AI客服无法解决您的问题，您可以申请转接人工客服。人工客服工作时间为工作日9:00-18:00，非工作时间您可以留言，我们会在24小时内回复。",
        "category": "其他",
        "tags": "人工客服,联系方式,工作时间"
    },
    {
        "question": "发票怎么开具？",
        "answer": "订单完成后，您可以在订单详情页申请开具电子发票。支持增值税普通发票和增值税专用发票。电子发票将在申请后2个工作日内发送至您的邮箱。",
        "category": "支付",
        "tags": "发票,电子发票,开票"
    },
    {
        "question": "如何取消订单？",
        "answer": "未发货的订单可以在订单详情页直接取消。已发货的订单无法直接取消，您可以在收到商品后申请退货退款。支付后30分钟内未发货的订单可无理由取消。",
        "category": "订单",
        "tags": "取消订单,退款"
    },
]


def seed():
    logger.info("初始化数据库表...")
    init_db()
    db = SessionLocal()

    try:
        existing = db.query(Tenant).filter_by(tenant_id="demo_001").first()
        if existing:
            logger.info("租户 demo_001 已存在，尝试同步FAQ到向量库...")
            logger.info(f"  API Key 前缀: {existing.api_key_prefix}")
            faq_count = db.query(FAQ).filter_by(tenant_id='demo_001').count()
            logger.info(f"  FAQ 数量: {faq_count}")
            if faq_count > 0:
                _sync_faqs_to_chromadb("demo_001", db)
            return

        logger.info("创建演示租户...")
        raw_key, hashed, prefix = generate_api_key()
        tenant = Tenant(
            tenant_id="demo_001",
            name="演示商家",
            api_key_hash=hashed,
            api_key_prefix=prefix,
        )
        db.add(tenant)
        db.flush()

        logger.info(f"  tenant_id: demo_001")
        logger.info(f"  API Key:   {raw_key}")
        logger.info(f"  (请妥善保存API Key，仅显示一次)")

        logger.info(f"\n创建 {len(DEMO_FAQS)} 条示例FAQ...")
        for faq_data in DEMO_FAQS:
            faq = FAQ(tenant_id="demo_001", **faq_data)
            db.add(faq)
        db.commit()

        logger.info("\n同步 FAQ 到 ChromaDB 向量库...")
        _sync_faqs_to_chromadb("demo_001", db)

        logger.info("种子数据创建完成！")
        logger.info(f"  API Key: {raw_key}")

    except Exception as e:
        db.rollback()
        logger.error(f"种子数据创建失败: {e}")
        raise
    finally:
        db.close()


def _sync_faqs_to_chromadb(tenant_id: str, db):
    """
    将数据库中的 FAQ 数据同步到 ChromaDB 新格式 collection
    """
    faqs = db.query(FAQ).filter_by(tenant_id=tenant_id).all()
    if not faqs:
        logger.info("  无FAQ数据，跳过同步")
        return

    embedding_model = get_embedding_model()

    ids = []
    documents = []
    metadatas = []
    embeddings = []

    for faq in faqs:
        content = f"Q: {faq.question}\nA: {faq.answer}"
        ids.append(f"faq_seed_{faq.id}")
        documents.append(content)
        metadatas.append({
            "kb_type": "faq",
            "source_id": f"faq_seed_{faq.id}",
            "category": faq.category or "",
            "tags": faq.tags or "",
        })

    embeddings = embedding_model.embed_documents(documents)

    clear_collection(tenant_id, "faq")
    add_to_collection_sync(
        tenant_id=tenant_id,
        kb_type="faq",
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )

    logger.info(f"  已同步 {len(documents)} 条FAQ到向量库 (kb_type=faq)")


if __name__ == "__main__":
    seed()
