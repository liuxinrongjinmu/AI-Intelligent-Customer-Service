"""
文档切片器 + 文本清洗
"""
import re
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LCDocument

from backend.config import DOC_CHUNK_SIZE, DOC_CHUNK_OVERLAP

# 常见的 PDF 导出水印/页眉/页脚噪声模式
_NOISE_PATTERNS = [
    re.compile(r"百度文库\s*[-—–]\s*好好学习[，,]\s*天天向上\s*"),
    re.compile(r"更多精彩内容请访问：?\s*https?://[^\s]*\s*"),
    re.compile(r"第\s*\d+\s*页\s*/\s*共\s*\d+\s*页\s*"),
]


def clean_text(text: str) -> str:
    """
    清洗文档文本：去除 PDF 导出水印、页眉页脚等噪声
    """
    if not text:
        return ""
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_text_splitter(
    chunk_size: int = DOC_CHUNK_SIZE,
    chunk_overlap: int = DOC_CHUNK_OVERLAP
) -> RecursiveCharacterTextSplitter:
    """
    获取中文友好的文本切片器

    :param chunk_size: 切片大小（字符数），默认从 config 读取
    :param chunk_overlap: 切片重叠（字符数），默认从 config 读取
    :return: RecursiveCharacterTextSplitter 实例
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        length_function=len,
    )


def split_documents(documents: list[LCDocument]) -> list[LCDocument]:
    """
    将文档切片为小块，并清洗噪声
    """
    for doc in documents:
        if hasattr(doc, 'page_content'):
            doc.page_content = clean_text(doc.page_content)

    splitter = get_text_splitter()
    return splitter.split_documents(documents)