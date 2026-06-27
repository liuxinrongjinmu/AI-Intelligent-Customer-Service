"""
高级功能工具：降级兜底 / A/B 测试框架 / 自动知识同步

兜底话术体系（6大类）：
  工具失败 / AI无法理解 / 安全 / 功能限制 / 情绪安抚 / 系统异常
"""
import random
from typing import Any


FALLBACK_RESPONSES = {
    # ==================== 工具调用失败 ====================
    "knowledge_no_result": "\u201c这个问题我暂时没找到相关信息，我来帮您查一下。\u201d",
    "api_timeout": "当前查询较繁忙，请稍后再试。如需即时帮助，可说\u201c转人工\u201d联系客服。",
    "order_not_found": "未查询到相关订单。请核实订单号后重试，或说\u201c转人工\u201d联系客服帮您查询。",
    "logistics_no_update": "物流信息暂未更新，可能是快递公司数据同步延迟或包裹尚在途中。建议过几小时刷新查看。",
    "product_not_found": "未找到相关商品。您可以提供更具体的商品名称，或说\u201c转人工\u201d联系客服协助查找。",
    "coupon_query_failed": "暂时无法查询优惠券信息，建议您在APP\u201c我的-优惠券\u201d中查看，或稍后再试。",
    "general_error": "抱歉，系统处理您的请求时出现了问题。请稍后再试，或说\u201c转人工\u201d联系客服。",

    # ==================== AI 无法理解 ====================
    "not_understood_1st": "抱歉，我没太理解您的问题。您可以换个方式描述一下吗？例如提供订单号或具体商品名，我能更快帮到您。",
    "not_understood_2nd": "还是没能准确理解您的问题，正在为您转接人工客服，请稍候。人工客服可以更精准地为您解答。",
    "empty_message": "您好！请问有什么可以帮您的？您可以咨询商品、订单、物流、售后等问题。",
    "too_long": "您的问题描述较长，能否简单概括一下核心问题？这样我能更快帮您找到答案。",
    "too_short": "您的问题描述较短，能否补充更多细节？方便我精准为您解答。",

    # ==================== 安全兜底 ====================
    "phone_detected": "为了您的信息安全，请勿在对话中直接发送手机号码。如有需要，可说明情况，客服会通过安全渠道联系您。",
    "id_card_detected": "请勿在对话中发送身份证号码等敏感信息。如有需要，客服会通过安全渠道核实您的身份。",
    "bank_card_detected": "请勿在对话中发送银行卡号。如需支付或退款，请在APP内完成操作。",
    "password_detected": "请勿在对话中发送密码等敏感信息。如需修改密码，建议在APP\u201c设置-账户安全\u201d中操作。",

    # ==================== 功能限制 ====================
    "image_not_supported": "目前暂不支持图片识别功能。您可以用文字描述问题，或说\u201c转人工\u201d联系客服处理。",
    "voice_not_supported": "目前暂不支持语音消息。请用文字描述您的问题，我会尽快为您解答。",
    "file_not_supported": "目前暂不支持文件上传。请用文字描述您的问题，或说\u201c转人工\u201d联系客服。",
    "non_ecommerce": "本平台主要提供电商相关服务。如您需要其他帮助，可以说\u201c转人工\u201d联系客服。",
    "complex_scene": "您的需求涉及复杂流程，正在为您转接人工客服，请稍候。人工客服能为您提供更细致的指导。",

    # ==================== 情绪安抚 ====================
    "user_impatient": "非常抱歉让您久等了！我马上给您答复。",
    "user_unsatisfied": "非常抱歉给您带来不好的体验！我会尽力为您解决问题。如果需要，您也可以说\u201c转人工\u201d联系客服。",
    "user_angry": "非常理解您的不满，给您带来困扰实在抱歉。我这边立刻为您转接人工客服优先处理，请稍候。",
    "user_demands_compensation": "理解您的心情，关于赔偿或补偿方案需要人工客服评估处理，我为您转接，请稍候。",
    "user_threatens": "理解您的问题很重要，我马上为您转接人工客服优先处理。人工客服可以提供更有针对性的解决方案。",

    # ==================== 系统异常 ====================
    "llm_unavailable": "系统正在维护中，AI客服暂时无法服务。请说\u201c转人工\u201d联系人工客服，或稍后再试。",
    "session_timeout": "由于您已有一段时间未发送消息，当前会话已超时。如需继续咨询，请重新描述您的问题。",
    "system_busy": "当前咨询量较大，响应可能稍慢。感谢您的耐心等待，我会尽快回复您。",

    # ==================== 通用 ====================
    "greeting": "您好！很高兴为您服务！有什么可以帮您的吗？",
    "other": "您好！请问有什么可以帮您的？您可以咨询商品信息、查询订单状态、了解物流进度等。",
    "goodbye": "感谢您的咨询！如有其他问题随时找我，祝您生活愉快！",
    "thanks": "不客气！如果还有其他问题随时找我。",
}


def get_fallback_response(category: str, sub_category: str = "") -> str:
    """
    获取兜底回复

    :param category: 兜底类别
    :param sub_category: 子类（可选）
    :return: 兜底话术
    """
    if sub_category:
        key = f"{category}_{sub_category}"
        if key in FALLBACK_RESPONSES:
            return FALLBACK_RESPONSES[key]
    if category in FALLBACK_RESPONSES:
        return FALLBACK_RESPONSES[category]
    return FALLBACK_RESPONSES["general_error"]


AB_TEST_VARIANTS = {
    "v1": {
        "label": "正式版",
        "temperature": 0.7,
        "max_tokens": 2048,
        "weight": 70,
    },
    "v2": {
        "label": "简洁版",
        "temperature": 0.3,
        "max_tokens": 512,
        "weight": 20,
    },
    "v3": {
        "label": "详细版",
        "temperature": 0.9,
        "max_tokens": 4096,
        "weight": 10,
    },
}


def get_ab_config() -> dict[str, Any]:
    """
    获取当前 A/B 测试配置（加权随机选择）

    通过 weight 控制流量分配，例如 v1:70%, v2:20%, v3:10%
    设置环境变量 AB_VARIANT 可强制指定版本（用于调试）

    每次选择后记录埋点，用于流量分配效果分析。
    强制模式下不记录埋点，避免调试流量污染 A/B 统计。
    """
    import os
    from backend.utils.metrics import record_ab_variant

    forced = os.getenv("AB_VARIANT", "")
    if forced and forced in AB_TEST_VARIANTS:
        # 强制模式不记录埋点，避免调试流量污染统计
        return AB_TEST_VARIANTS[forced]

    variants = list(AB_TEST_VARIANTS.items())
    weights = [v[1]["weight"] for v in variants]
    total_weight = sum(weights)
    if total_weight == 0:
        _safe_record_ab("v1")
        return AB_TEST_VARIANTS["v1"]

    r = random.uniform(0, total_weight)
    cumulative = 0
    for name, config in variants:
        cumulative += config["weight"]
        if r <= cumulative:
            _safe_record_ab(name)
            return config

    _safe_record_ab("v1")
    return AB_TEST_VARIANTS["v1"]


def _safe_record_ab(variant: str):
    """
    安全记录 A/B 埋点（异常不影响主流程）

    :param variant: 分桶名称
    """
    try:
        from backend.utils.metrics import record_ab_variant
        record_ab_variant(variant)
    except Exception:
        pass