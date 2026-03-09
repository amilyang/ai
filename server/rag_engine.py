'''
Author: e0042176 e0042176@ceic.com
Date: 2026-03-09 15:06:46
LastEditors: e0042176 e0042176@ceic.com
LastEditTime: 2026-03-09 15:52:42
FilePath: \ai\server\rag_engine.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
# server/rag_engine.py
import os
import chromadb
from dashscope import TextEmbedding
import dotenv

dotenv.load_dotenv()

# 初始化 ChromaDB (持久化存储在当前目录的 chroma_db 文件夹)
chroma_client = chromadb.PersistentClient(path="./chroma_db")

# 获取或创建集合 (Collection)
collection = chroma_client.get_or_create_collection(name="knowledge_base")

def get_embedding(text: str):
    """调用阿里云 DashScope 获取文本向量"""
    response = TextEmbedding.call(
        model="text-embedding-v2",
        input=text
    )
    if response.status_code == 200:
        # 返回第一个结果的向量
        return response.output['embeddings'][0]['embedding']
    else:
        print(f"Embedding Error: {response.message}")
        return None

def add_document(doc_text: str, doc_id: str, metadata: dict = None):
    """
    将文档切片并存入向量库
    简单起见，这里我们按固定字符数切片（生产环境建议按段落或递归字符切片）
    """
    chunk_size = 500
    chunks = []
    ids = []
    metadatas = []
    embeddings = []

    # 简单的切片逻辑
    for i in range(0, len(doc_text), chunk_size):
        chunk = doc_text[i:i+chunk_size]
        if not chunk.strip():
            continue

        chunk_id = f"{doc_id}_{i}"
        emb = get_embedding(chunk)

        if emb:
            chunks.append(chunk)
            ids.append(chunk_id)
            metadatas.append(metadata or {"source": "uploaded"})
            embeddings.append(emb)

    if chunks:
        collection.add(
            documents=chunks,
            ids=ids,
            metadatas=metadatas,
            embeddings=embeddings
        )
        return True
    return False

def query_knowledge(query: str, n_results: int = 3):
    """检索最相关的知识片段"""
    query_emb = get_embedding(query)
    if not query_emb:
        return []

    results = collection.query(
        query_embeddings=[query_emb],
        n_results=n_results
    )

    # 返回文档内容列表
    return results['documents'][0] if results['documents'] else []