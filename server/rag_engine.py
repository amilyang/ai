# server/rag_engine.py
import os
import chromadb
from dashscope import TextEmbedding
from rank_bm25 import BM25Okapi
import numpy as np
from typing import List, Dict
import re

# 1. 初始化 ChromaDB
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="knowledge_base")

# 2. 内存中的 BM25 索引 (简单起见，每次启动重新构建，生产环境需持久化)
bm25_index = None
bm25_texts = []

def get_embedding(text: str):
    response = TextEmbedding.call(model="text-embedding-v2", input=text)
    if response.status_code == 200:
        return response.output['embeddings'][0]['embedding']
    return None

def preprocess_text(text):
    # 简单的分词，中文可以使用 jieba，这里为了演示用空格和正则简单处理
    return re.findall(r'\w+', text.lower())

def build_bm25_index():
    global bm25_index, bm25_texts
    # 获取所有文档
    all_docs = collection.get(include=['documents'])
    bm25_texts = all_docs['documents']
    if bm25_texts:
        # 实际中文项目建议用 jieba.analyse 或 jieba.cut 进行分词
        tokenized_docs = [preprocess_text(t) for t in bm25_texts]
        bm25_index = BM25Okapi(tokenized_docs)
        print(f"✅ BM25 索引已重建，共 {len(bm25_texts)} 个片段")

def add_document(texts: List[str], ids: List[str], metadatas: List[Dict]):
    # 1. 获取向量
    embeddings = []
    for text in texts:
        emb = get_embedding(text)
        if emb: embeddings.append(emb)

    if not embeddings: return False

    # 2. 存入 Chroma
    collection.add(documents=texts, ids=ids, metadatas=metadatas, embeddings=embeddings)

    # 3. 重建 BM25 索引
    build_bm25_index()
    return True

def query_knowledge(query: str, top_k: int = 3):
    # === 阶段 1: 向量检索 (召回 10 个) ===
    query_emb = get_embedding(query)
    vector_results = collection.query(query_embeddings=[query_emb], n_results=10)
    vector_docs = vector_results['documents'][0]
    vector_ids = vector_results['ids'][0]

    # === 阶段 2: BM25 关键词检索 (召回 10 个) ===
    bm25_results = []
    if bm25_index:
        query_tokens = preprocess_text(query)
        scores = bm25_index.get_scores(query_tokens)
        # 取前 10 个高分
        top_indices = np.argsort(scores)[::-1][:10]
        for idx in top_indices:
            if scores[idx] > 0: # 过滤掉 0 分
                bm25_results.append({
                    "id": collection.get(ids=[collection.get()['ids'][idx]])['ids'][0], # 这里简化处理，实际需对应
                    "text": bm25_texts[idx],
                    "score": scores[idx]
                })

    # === 阶段 3: 合并与去重 ===
    # 简单合并，实际项目中需要更复杂的去重逻辑
    all_candidates = []

    # 添加向量检索结果
    for doc, doc_id in zip(vector_docs, vector_ids):
        all_candidates.append({"id": doc_id, "text": doc, "source": "vector"})

    # 添加 BM25 结果 (这里为了演示简化了 ID 获取，实际应直接从 collection 获取)
    # 注意：上面的 bm25 获取 ID 方式在 Chroma 中比较复杂，
    # 实际建议直接遍历 bm25_texts 并匹配索引。
    # 这里我们直接用文本内容去重。
    existing_texts = set([c['text'] for c in all_candidates])
    for item in bm25_results:
        if item['text'] not in existing_texts:
            all_candidates.append({"id": f"bm25_{item['id']}", "text": item['text'], "source": "bm25"})

    # === 阶段 4: 重排序 (Re-ranking) ===
    # 这里模拟 Re-ranker 效果。
    # 真正的 Re-ranker 需要调用 Cross-Encoder 模型 (如 BGE-Reranker)。
    # 为了演示，我们假设向量检索的结果权重更高，或者简单截断。
    # 如果你有 BGE-Reranker API，可以在这里调用，输入 query 和所有 candidate texts，获取分数排序。

    # 简单策略：优先取向量检索的结果，如果不够，再补 BM25 的
    final_results = []
    seen_texts = set()

    # 先加向量结果
    for item in all_candidates:
        if item['source'] == 'vector' and item['text'] not in seen_texts:
            final_results.append(item['text'])
            seen_texts.add(item['text'])

    # 再加 BM25 结果 (补充多样性)
    for item in all_candidates:
        if item['source'] == 'bm25' and item['text'] not in seen_texts:
            final_results.append(item['text'])
            seen_texts.add(item['text'])

    return final_results[:top_k] # 返回前 top_k 个