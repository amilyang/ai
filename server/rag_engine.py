# server/rag_engine.py
import os
import chromadb
from dashscope import TextEmbedding
from rank_bm25 import BM25Okapi
import numpy as np
from typing import List, Dict
import re
import jieba
import joblib
from sentence_transformers import CrossEncoder

# 1. 初始化 ChromaDB 客户端，创建/获取名为 "knowledge_base" 的集合
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="knowledge_base")

# 2. 全局变量
BM25_INDEX_PATH = "./bm25_index.joblib"  # BM25 索引持久化路径
bm25_index = None  # BM25 索引对象
bm25_texts = []  # 存储文档文本，与bm25_ids对应
bm25_ids = []  # 存储文档ID，与bm25_texts对应
reranker = None  # BGE-Reranker模型对象
query_cache = {}  # 查询缓存，用于存储最近查询结果

# 3. 加载 BGE-Reranker 模型
def load_reranker():
    global reranker
    try:
        # 使用 sentence-transformers 加载 BGE-Reranker
        reranker = CrossEncoder('BAAI/bge-reranker-large', max_length=512)
        print("✅ BGE-Reranker 模型已加载")
    except Exception as e:
        print(f"⚠️  无法加载 BGE-Reranker 模型: {e}")
        reranker = None

# 4. 文本预处理（使用 jieba 分词）
def preprocess_text(text):
    # 中文分词
    return list(jieba.cut(text))

# 5. 构建并持久化 BM25 索引
def build_bm25_index():
    global bm25_index, bm25_texts, bm25_ids
    # 获取所有文档
    all_docs = collection.get(include=['documents', 'ids'])  # 获取所有文档和ID
    print(f"✅ 从 ChromaDB 获取 {len(all_docs['documents'])} 个文档")
    bm25_texts = all_docs['documents']
    bm25_ids = all_docs['ids']

    if bm25_texts:
        # 使用 jieba 进行中文分词
        tokenized_docs = [preprocess_text(t) for t in bm25_texts]  # 对文档进行分词
        bm25_index = BM25Okapi(tokenized_docs)  # 构建 BM25 索引

        # 持久化索引
        try:
            joblib.dump((bm25_index, bm25_texts, bm25_ids), BM25_INDEX_PATH)  # 持久化索引
            print(f"✅ BM25 索引已重建并持久化，共 {len(bm25_texts)} 个片段")
        except Exception as e:
            print(f"⚠️  无法持久化 BM25 索引: {e}")

# 6. 加载 BM25 索引
def load_bm25_index():
    global bm25_index, bm25_texts, bm25_ids
    if os.path.exists(BM25_INDEX_PATH):
        try:
            bm25_index, bm25_texts, bm25_ids = joblib.load(BM25_INDEX_PATH)
            print(f"✅ 从磁盘加载 BM25 索引，共 {len(bm25_texts)} 个片段")
        except Exception as e:
            print(f"⚠️  无法加载 BM25 索引: {e}")
            build_bm25_index()
    else:
        build_bm25_index()

# 7. 获取文本向量
def get_embedding(text: str):
    """获取文本向量，优先使用本地模型"""
    # 尝试导入本地嵌入模型
    try:
        from main import load_local_embedding_model
        local_model = load_local_embedding_model()
        if local_model:
            try:
                embedding = local_model.encode(text).tolist()
                print("[OK] 使用本地嵌入模型成功")
                return embedding
            except Exception as e:
                print(f"[WARN] 本地嵌入模型失败: {e}")
    except Exception as e:
        print(f"[WARN] 无法导入本地嵌入模型: {e}")

    # 尝试使用阿里云 API
    response = TextEmbedding.call(model="text-embedding-v4", input=text)
    if response.status_code == 200:
        return response.output['embeddings'][0]['embedding']
    return None

# 8. 添加文档
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
    # 4. 清空查询缓存
    global query_cache
    query_cache = {}
    return True

# 9. 查询知识
def query_knowledge(query: str, top_k: int = 3):
    # 检查缓存
    cache_key = f"{query}_{top_k}"  # 缓存键，包含查询文本和 top_k
    if cache_key in query_cache:
        print("✅ 从缓存获取查询结果")
        return query_cache[cache_key]

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
                    "id": bm25_ids[idx],
                    "text": bm25_texts[idx],
                    "score": scores[idx]
                })

    # === 阶段 3: 合并与去重 ===
    all_candidates = []

    # 添加向量检索结果
    for doc, doc_id in zip(vector_docs, vector_ids):
        all_candidates.append({"id": doc_id, "text": doc, "source": "vector"})

    # 添加 BM25 结果
    existing_texts = set([c['text'] for c in all_candidates])
    for item in bm25_results:
        if item['text'] not in existing_texts:
            all_candidates.append({"id": item['id'], "text": item['text'], "source": "bm25"})

    # === 阶段 4: 重排序 (Re-ranking) ===
    final_results = []

    if reranker and all_candidates:
        # 使用 BGE-Reranker 进行重排序
        print("✅ 使用 BGE-Reranker 进行重排序")
        pairs = [(query, candidate['text']) for candidate in all_candidates]
        scores = reranker.predict(pairs)

        # 按分数排序
        ranked_candidates = sorted(
            zip(scores, all_candidates),
            key=lambda x: x[0],
            reverse=True
        )

        # 去重并取前 top_k 个
        seen_texts = set()
        for score, candidate in ranked_candidates:
            if candidate['text'] not in seen_texts:
                final_results.append(candidate['text'])
                seen_texts.add(candidate['text'])
                if len(final_results) >= top_k:
                    break
    else:
        # 简单策略：优先取向量检索的结果，如果不够，再补 BM25 的
        seen_texts = set()

        # 先加向量结果
        for item in all_candidates:
            if item['source'] == 'vector' and item['text'] not in seen_texts:
                final_results.append(item['text'])
                seen_texts.add(item['text'])
                if len(final_results) >= top_k:
                    break

        # 再加 BM25 结果 (补充多样性)
        if len(final_results) < top_k:
            for item in all_candidates:
                if item['source'] == 'bm25' and item['text'] not in seen_texts:
                    final_results.append(item['text'])
                    seen_texts.add(item['text'])
                    if len(final_results) >= top_k:
                        break

    # 缓存结果
    query_cache[cache_key] = final_results
    # 限制缓存大小
    if len(query_cache) > 100:
        # 删除最旧的缓存
        oldest_key = next(iter(query_cache))
        del query_cache[oldest_key]

    return final_results[:top_k] # 返回前 top_k 个

# 初始化
load_bm25_index()
load_reranker()