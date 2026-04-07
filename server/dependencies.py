from database import init_chroma
from config import CHROMA_PERSIST_DIR

# 初始化向量数据库
chroma_collection = init_chroma(CHROMA_PERSIST_DIR)

async def get_chroma_collection():
    """获取ChromaDB集合"""
    return chroma_collection
