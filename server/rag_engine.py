# server/rag_engine.py
import os
import dotenv
import chromadb
from dashscope import TextEmbedding
from dashscope import TextReRank
import dashscope
from rank_bm25 import BM25Okapi
import numpy as np
from typing import List, Dict
import re
import jieba
import joblib

# Load environment variables from .env file
dotenv.load_dotenv()

# Set DashScope API key
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "")

# 1. Initialize ChromaDB client
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="knowledge_base")

# 2. Global variables
BM25_INDEX_PATH = "./bm25_index.joblib"
bm25_index = None
bm25_texts = []
bm25_ids = []
reranker = None
query_cache = {}
embedding_dimension = 1024

# 3. Load Reranker model
def load_reranker():
    global reranker
    try:
        # Check if DashScope API key is available
        if dashscope.api_key:
            print("Using Bailian platform Rerank API")
            # We'll use the Rerank class directly
            reranker = "bailian_rerank"
            print("Bailian Rerank API configured successfully")
            return

        # If no API key, use simple ranking
        print("No DashScope API key, will use simple ranking")
        reranker = None
    except Exception as e:
        print(f"Error in load_reranker: {e}")
        reranker = None

# 4. Text preprocessing
def preprocess_text(text):
    return list(jieba.cut(text))

# 5. Build and persist BM25 index
def build_bm25_index():
    global bm25_index, bm25_texts, bm25_ids
    all_docs = collection.get(include=['documents'])
    print(f"Got {len(all_docs['documents'])} documents from ChromaDB")
    bm25_texts = all_docs['documents']
    bm25_ids = [f"doc_{i}" for i in range(len(bm25_texts))]

    if bm25_texts:
        tokenized_docs = [preprocess_text(t) for t in bm25_texts]
        bm25_index = BM25Okapi(tokenized_docs)

        try:
            joblib.dump((bm25_index, bm25_texts, bm25_ids), BM25_INDEX_PATH)
            print(f"BM25 index rebuilt and persisted, {len(bm25_texts)} segments")
        except Exception as e:
            print(f"Failed to persist BM25 index: {e}")

# 6. Load BM25 index
def load_bm25_index():
    global bm25_index, bm25_texts, bm25_ids
    if os.path.exists(BM25_INDEX_PATH):
        try:
            bm25_index, bm25_texts, bm25_ids = joblib.load(BM25_INDEX_PATH)
            print(f"Loaded BM25 index from disk, {len(bm25_texts)} segments")
        except Exception as e:
            print(f"Failed to load BM25 index: {e}")
            build_bm25_index()
    else:
        build_bm25_index()

# 7. Get text embedding
def get_embedding(text: str):
    try:
        response = TextEmbedding.call(model="text-embedding-v4", input=text)
        if response.status_code == 200:
            print("[OK] DashScope embedding API used successfully")
            return response.output['embeddings'][0]['embedding']
    except Exception as e:
        print(f"[WARN] DashScope API failed: {e}")

    print("[WARN] Using zero vector as fallback")
    return [0.0] * embedding_dimension

# 8. Add document
def add_document(texts: List[str], ids: List[str], metadatas: List[Dict]):
    embeddings = []
    for text in texts:
        emb = get_embedding(text)
        if emb:
            embeddings.append(emb)

    if not embeddings:
        return False

    collection.add(documents=texts, ids=ids, metadatas=metadatas, embeddings=embeddings)
    build_bm25_index()
    global query_cache
    query_cache = {}
    return True

# 9. Query knowledge
def query_knowledge(query: str, top_k: int = 3):
    cache_key = f"{query}_{top_k}"
    if cache_key in query_cache:
        print("Cache hit, returning cached results")
        return query_cache[cache_key]

    # Vector search
    vector_docs = []
    vector_ids = []
    try:
        query_emb = get_embedding(query)
        vector_results = collection.query(query_embeddings=[query_emb], n_results=10)
        vector_docs = vector_results['documents'][0]
        vector_ids = vector_results['ids'][0]
        print(f"Vector search returned {len(vector_docs)} results")
    except Exception as e:
        print(f"[WARN] Vector search failed, will use BM25 only: {e}")
        vector_docs = []
        vector_ids = []

    # BM25 search
    bm25_results = []
    if bm25_index:
        query_tokens = preprocess_text(query)
        scores = bm25_index.get_scores(query_tokens)
        top_indices = np.argsort(scores)[::-1][:10]
        for idx in top_indices:
            if scores[idx] > 0:
                bm25_results.append({
                    "id": bm25_ids[idx],
                    "text": bm25_texts[idx],
                    "score": scores[idx]
                })

    # Merge and deduplicate
    all_candidates = []
    for doc, doc_id in zip(vector_docs, vector_ids):
        all_candidates.append({"id": doc_id, "text": doc, "source": "vector"})

    existing_texts = set([c['text'] for c in all_candidates])
    for item in bm25_results:
        if item['text'] not in existing_texts:
            all_candidates.append({"id": item['id'], "text": item['text'], "source": "bm25"})

    # Re-ranking
    final_results = []
    if reranker and all_candidates:
        if reranker == "bailian_rerank":
            print("Using Bailian platform TextReRank API")
            try:
                # Prepare documents for TextReRank API
                documents = [candidate['text'] for candidate in all_candidates]

                # Call Bailian TextReRank API
                response = TextReRank.call(
                    model=TextReRank.Models.gte_rerank,  # Use the available model
                    query=query,
                    documents=documents,
                    top_n=top_k * 2,  # Get more results to ensure we have enough after deduplication
                    return_documents=True  # Return the documents
                )

                if response.status_code == 200:
                    print("Bailian TextReRank API call successful")
                    # Process results
                    ranked_candidates = []
                    for item in response.output['results']:
                        doc_idx = item['index']
                        if doc_idx < len(all_candidates):
                            ranked_candidates.append(all_candidates[doc_idx])
                else:
                    print(f"Bailian TextReRank API failed: {response.message}")
                    ranked_candidates = all_candidates
            except Exception as e:
                print(f"Error using Bailian TextReRank API: {e}")
                ranked_candidates = all_candidates

            seen_texts = set()
            for candidate in ranked_candidates:
                if candidate['text'] not in seen_texts:
                    final_results.append(candidate['text'])
                    seen_texts.add(candidate['text'])
                    if len(final_results) >= top_k:
                        break
    else:
        seen_texts = set()
        for item in all_candidates:
            if item['source'] == 'vector' and item['text'] not in seen_texts:
                final_results.append(item['text'])
                seen_texts.add(item['text'])
                if len(final_results) >= top_k:
                    break

        if len(final_results) < top_k:
            for item in all_candidates:
                if item['source'] == 'bm25' and item['text'] not in seen_texts:
                    final_results.append(item['text'])
                    seen_texts.add(item['text'])
                    if len(final_results) >= top_k:
                        break

    query_cache[cache_key] = final_results
    if len(query_cache) > 100:
        oldest_key = next(iter(query_cache))
        del query_cache[oldest_key]

    return final_results[:top_k]

# Initialize
load_bm25_index()
load_reranker()
