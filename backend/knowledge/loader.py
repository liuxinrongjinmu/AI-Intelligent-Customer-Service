"""
文档加载器：支持 PDF、TXT、Markdown 格式
"""
import logging
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document as LCDocument

logger = logging.getLogger(__name__)


def load_pdf(file_path: str) -> list[LCDocument]:
    """
    加载 PDF 文件
    """
    try:
        return PyPDFLoader(file_path).load()
    except Exception as e:
        logger.error(f"加载PDF文件失败: {file_path}, {e}")
        return []


def load_txt(file_path: str) -> list[LCDocument]:
    """
    加载 TXT 文件
    """
    try:
        return TextLoader(file_path, encoding="utf-8").load()
    except Exception as e:
        logger.error(f"加载TXT文件失败: {file_path}, {e}")
        return []


def load_markdown(file_path: str) -> list[LCDocument]:
    """
    加载 Markdown 文件（作为纯文本）
    """
    try:
        return TextLoader(file_path, encoding="utf-8").load()
    except Exception as e:
        logger.error(f"加载Markdown文件失败: {file_path}, {e}")
        return []


def load_document(file_path: str, file_type: str) -> list[LCDocument]:
    """
    根据文件类型加载文档
    """
    loaders = {
        "pdf": load_pdf,
        "txt": load_txt,
        "md": load_markdown,
    }
    loader = loaders.get(file_type)
    if not loader:
        raise ValueError(f"不支持的文件类型: {file_type}")
    return loader(file_path)