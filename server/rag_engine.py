# server/rag_engine.py
import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
import numpy as np
import pdfplumber
import re

class AdvancedRAGEngine:
    def __init__(self, persist_directory="./db"):
        # 1. 向量数据库 (保持原有)
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection("advanced_rag")

        # 2. BM25 索引 (关键词)
        self.bm25_index = None
        self.documents_map = {} # 映射 ID -> 原文内容

        # 3. Re-ranker 模型 (使用跨编码器进行精细排序)
        # 推荐模型: BAAI/bge-reranker-base (中文效果好) 或 cross-encoder/ms-marco-MiniLM-L-6-v2
        print("Loading Re-ranker model...")
        self.reranker = CrossEncoder('BAAI/bge-reranker-base', device='cpu') # 有 GPU 可改为 'cuda'
        print("Re-ranker loaded.")

    def preprocess_text(self, text):
        """简单的文本清洗"""
        return re.sub(r'\s+', ' ', text).strip()

    def ingest_pdf_advanced(self, file_path, metadata):
        """
        高级 PDF 解析：使用 pdfplumber 更好地处理表格和布局
        """
        chunks = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # 策略：先提取表格，再提取文本
                tables = page.extract_tables()
                for table in tables:
                    # 将表格转换为 Markdown 格式，LLM 更容易理解
                    md_table = "\n".join(["| " + " | ".join([str(cell) for cell in row]) + " |" for row in table])
                    chunks.append({
                        "content": f"[Table from Page {i+1}]\n{md_table}",
                        "metadata": {**metadata, "page": i+1, "type": "table"}
                    })

                # 提取普通文本
                text = page.extract_text()
                if text:
                    # 简单的按段落分块 (实际生产中可用更复杂的递归分块)
                    paragraphs = text.split('\n\n')
                    for p in paragraphs:
                        if len(p.strip()) > 50: # 过滤太短的片段
                            chunks.append({
                                "content": self.preprocess_text(p),
                                "metadata": {**metadata, "page": i+1, "type": "text"}
                            })

        # 存入向量库
        if chunks:
            self.collection.add(
                documents=[c["content"] for c in chunks],
                metadatas=[c["metadata"] for c in chunks],
                ids=[f"{metadata['source']}_{i}" for i in range(len(chunks))]
            )

            # 更新 BM25 索引
            self._update_bm25([c["content"] for c in chunks], [f"{metadata['source']}_{i}" for i in range(len(chunks))])

        return len(chunks)

    def _update_bm25(self, new_docs, new_ids):
        """更新 BM25 索引"""
        # 简单策略：重新构建整个索引 (数据量大时需用增量更新或持久化存储)
        all_docs = []
        all_ids = []

        # 合并现有文档
        for doc_id, doc in self.documents_map.items():
            all_docs.append(doc)
            all_ids.append(doc_id)

        # 添加新文档
        for doc, doc_id in zip(new_docs, new_ids):
            self.documents_map[doc_id] = doc
            all_docs.append(doc)
            all_ids.append(doc_id)

        # 分词 (中文需要简单分词，这里用空格模拟，生产环境建议用 jieba)
        tokenized_docs = [doc.split() for doc in all_docs]
        self.bm25_index = BM25Okapi(tokenized_docs)
        self.bm25_ids = all_ids

    def retrieve(self, query, top_k=5):
        """
        混合检索 + 重排序流程
        """
        # 1. 向量检索 (Dense Retrieval) - 捕捉语义
        vector_results = self.collection.query(
            query_texts=[query],
            n_results=top_k * 2 # 先多取一些，供重排序筛选
        )

        # 2. BM25 检索 (Sparse Retrieval) - 捕捉精确关键词
        bm25_scores = []
        if self.bm25_index:
            tokenized_query = query.split()
            scores = self.bm25_index.get_scores(tokenized_query)
            # 获取 Top K 的 BM25 结果
            top_indices = np.argsort(scores)[::-1][:top_k * 2]
            bm25_results = {
                "ids": [[self.bm25_ids[i]] for i in top_indices],
                "documents": [[self.documents_map[self.bm25_ids[i]]] for i in top_indices],
                "distances": [[scores[i]] for i in top_indices] # 分数越高越好
            }
        else:
            bm25_results = {"ids": [[]], "documents": [[]], "distances": [[]]}

        # 3. 融合结果 (Reciprocal Rank Fusion 或 简单去重合并)
        # 这里采用简单合并去重策略
        seen_ids = set()
        merged_candidates = []

        # 添加向量结果
        for id, doc in zip(vector_results['ids'][0], vector_results['documents'][0]):
            if id not in seen_ids:
                merged_candidates.append({"id": id, "content": doc, "source": "vector"})
                seen_ids.add(id)

        # 添加 BM25 结果
        for id, doc in zip(bm25_results['ids'][0], bm25_results['documents'][0]):
            if id not in seen_ids:
                merged_candidates.append({"id": id, "content": doc, "source": "bm25"})
                seen_ids.add(id)

        if not merged_candidates:
            return []

        # 4. 重排序 (Re-ranking) - 关键步骤!
        # 使用 CrossEncoder 对 (Query, Document) 对进行打分
        pairs = [[query, cand["content"]] for cand in merged_candidates]
        rerank_scores = self.reranker.predict(pairs)

        # 附加分数到候选项
        for i, score in enumerate(rerank_scores):
            merged_candidates[i]["score"] = score

        # 5. 按重排序分数降序排列，取最终 Top K
        final_results = sorted(merged_candidates, key=lambda x: x["score"], reverse=True)[:top_k]

        return final_results