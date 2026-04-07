import base64
from io import BytesIO
from PIL import Image
import pytesseract
from typing import List, Tuple, Optional
from utils.embedding import get_embedding
from config import MAX_RELEVANT_CHUNKS

def process_images(images: Optional[List[str]]):
    """处理图片内容，提取文本
    
    Args:
        images: 图片列表
    
    Returns:
        tuple: (image_context, is_valid)
    """
    image_context = []
    is_valid = True
    if images and len(images) > 0:
        for i, image in enumerate(images):
            try:
                # 检查是否为字符串格式
                if not isinstance(image, str):
                    image_context.append(f"[图片 {i+1} 文本内容]\n（非字符串格式，跳过处理）\n")
                    is_valid = False
                    continue

                # 检查字符串是否为空
                if not image.strip():
                    image_context.append(f"[图片 {i+1} 文本内容]\n（空字符串，跳过处理）\n")
                    is_valid = False
                    continue

                # 检查是否为base64格式
                if image.startswith('data:image/'):
                    # 移除base64前缀
                    try:
                        image_data = image.split(',')[1]
                    except Exception as e:
                        image_context.append(f"[图片 {i+1} 文本内容]\n（格式错误，跳过处理）\n")
                        is_valid = False
                        continue
                else:
                    image_data = image

                # 尝试解码base64
                try:
                    image_bytes = base64.b64decode(image_data)
                except Exception as e:
                    image_context.append(f"[图片 {i+1} 文本内容]\n（base64解码失败，跳过处理）\n")
                    is_valid = False
                    continue

                # 尝试打开图片
                try:
                    img = Image.open(BytesIO(image_bytes))
                except Exception as e:
                    image_context.append(f"[图片 {i+1} 文本内容]\n（图片打开失败，跳过处理）\n")
                    is_valid = False
                    continue

                # 尝试使用tesseract进行OCR
                try:
                    # 检查tesseract是否可用
                    import subprocess
                    result = subprocess.run(['tesseract', '--version'], capture_output=True, timeout=5)
                    if result.returncode != 0:
                        raise Exception("tesseract not available")

                    ocr_text = pytesseract.image_to_string(img, lang='chi_sim+eng')
                    if ocr_text.strip():
                        image_context.append(f"[图片 {i+1} 文本内容]\n{ocr_text}\n")
                    else:
                        image_context.append(f"[图片 {i+1} 文本内容]\n（未提取到文本）\n")
                except Exception as ocr_error:
                    image_context.append(f"[图片 {i+1} 文本内容]\n（OCR处理失败，可能需要安装tesseract）\n")
                    # OCR失败不影响整体有效性
            except Exception as e:
                image_context.append(f"[图片 {i+1} 文本内容]\n（处理失败）\n")
                is_valid = False
    return image_context, is_valid

def retrieve_relevant_knowledge(query: str, chroma_collection):
    """检索相关知识，包括向量检索、BM25检索、合并去重和重排序
    
    Args:
        query: 查询文本
        chroma_collection: ChromaDB集合
    
    Returns:
        tuple: (relevant_chunks, chunk_sources)
    """
    relevant_chunks = []
    chunk_sources = []  # 存储知识来源信息
    try:
        # 1. 向量检索 (召回 10 个)
        print("[INFO] 开始向量检索")
        query_emb = get_embedding(query)
        vector_results = {}
        if query_emb:
            results = chroma_collection.query(
                query_embeddings=[query_emb],
                n_results=10,  # 召回 10 个
                include=['documents', 'metadatas', 'distances']
            )
            if results and results['documents'] and results['distances']:
                vector_results = {
                    'documents': results['documents'][0],
                    'metadatas': results['metadatas'][0] if results['metadatas'] else [{}] * len(results['documents'][0]),
                    'distances': results['distances'][0]
                }
                print(f"[INFO] 向量检索完成，找到 {len(vector_results['documents'])} 个结果")

        # 2. BM25 关键词检索 (召回 10 个)
        print("[INFO] 开始 BM25 关键词检索")
        bm25_results = []
        try:
            from rank_bm25 import BM25Okapi
            import jieba

            # 获取所有文档
            all_docs = chroma_collection.get(include=['documents', 'metadatas'])
            if all_docs and all_docs['documents']:
                # 中文分词
                tokenized_docs = [list(jieba.cut(doc)) for doc in all_docs['documents']]
                bm25 = BM25Okapi(tokenized_docs)

                # 对查询进行分词
                tokenized_query = list(jieba.cut(query))
                scores = bm25.get_scores(tokenized_query)

                # 取前 10 个高分
                top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:10]

                for idx in top_indices:
                    if scores[idx] > 0:  # 过滤掉 0 分
                        bm25_results.append({
                            'document': all_docs['documents'][idx],
                            'metadata': all_docs['metadatas'][idx] if all_docs['metadatas'] else {},
                            'score': scores[idx]
                        })

                print(f"[INFO] BM25 检索完成，找到 {len(bm25_results)} 个结果")
        except Exception as e:
            print(f"[ERROR] BM25 检索失败: {e}")

        # 3. 合并与去重
        print("[INFO] 开始合并与去重")
        all_chunks = []
        all_metadatas = []
        seen_chunks = set()

        # 添加向量检索结果
        if vector_results:
            for doc, metadata in zip(vector_results['documents'], vector_results['metadatas']):
                if doc not in seen_chunks:
                    all_chunks.append(doc)
                    all_metadatas.append(metadata)
                    seen_chunks.add(doc)

        # 添加 BM25 检索结果
        for item in bm25_results:
            if item['document'] not in seen_chunks:
                all_chunks.append(item['document'])
                all_metadatas.append(item['metadata'])
                seen_chunks.add(item['document'])

        print(f"[INFO] 合并去重后，共 {len(all_chunks)} 个结果")

        # 4. 重排序 (Re-ranking) - 使用向量相似度和BM25分数的组合排序
        print("[INFO] 开始重排序")
        if all_chunks:
            try:
                # 构建组合分数
                chunk_scores = []

                for i, chunk in enumerate(all_chunks):
                    # 向量相似度分数（距离越小越相似，需要转换为分数）
                    vector_score = 0.0
                    if vector_results and i < len(vector_results['distances']):
                        # 将距离转换为相似度分数（距离越小，分数越高）
                        distance = vector_results['distances'][i]
                        vector_score = 1.0 / (1.0 + distance)  # 归一化到0-1之间

                    # BM25分数
                    bm25_score = 0.0
                    for bm25_item in bm25_results:
                        if bm25_item['document'] == chunk:
                            # 归一化BM25分数（假设最大分数为10）
                            bm25_score = min(bm25_item['score'] / 10.0, 1.0)
                            break

                    # 组合分数（向量相似度权重0.6，BM25权重0.4）
                    combined_score = 0.6 * vector_score + 0.4 * bm25_score
                    chunk_scores.append((combined_score, chunk, all_metadatas[i]))

                    print(f"[DEBUG] 片段 {i+1}: 向量分数={vector_score:.4f}, BM25分数={bm25_score:.4f}, 组合分数={combined_score:.4f}")

                # 按组合分数排序（分数越高越相关）
                chunk_scores.sort(key=lambda x: x[0], reverse=True)
                sorted_chunks = [item[1] for item in chunk_scores]
                sorted_metadatas = [item[2] for item in chunk_scores]

                print("[INFO] 使用向量相似度和BM25分数组合进行重排序")
            except Exception as e:
                print(f"[ERROR] 组合排序失败: {e}")
                # 回退到基于向量距离排序
                if vector_results:
                    # 基于向量距离排序
                    sorted_indices = sorted(range(len(all_chunks)), key=lambda i: vector_results['distances'][i] if i < len(vector_results['distances']) else float('inf'))
                    sorted_chunks = [all_chunks[i] for i in sorted_indices]
                    sorted_metadatas = [all_metadatas[i] for i in sorted_indices]
                else:
                    # 直接使用合并结果
                    sorted_chunks = all_chunks
                    sorted_metadatas = all_metadatas
                print("[INFO] 回退到基于距离排序")

            # 限制最终结果数量
            relevant_chunks = sorted_chunks[:MAX_RELEVANT_CHUNKS]
            chunk_sources = sorted_metadatas[:MAX_RELEVANT_CHUNKS]

            print(f"[INFO] 最终检索到 {len(relevant_chunks)} 个相关知识片段")
    except Exception as e:
        print(f"RAG Search Error: {e}")
    return relevant_chunks, chunk_sources

def build_context(relevant_chunks: list, chunk_sources: list, image_context: list):
    """构建对话上下文
    
    Args:
        relevant_chunks: 相关知识片段
        chunk_sources: 知识来源信息
        image_context: 图片上下文
    
    Returns:
        str: 上下文字符串
    """
    context_str = ""
    if relevant_chunks:
        context_str = "以下是相关的背景知识，请依据这些知识回答问题：\n\n"
        for i, (chunk, source) in enumerate(zip(relevant_chunks, chunk_sources)):
            # 知识来源标注
            source_info = ""
            if source:
                if source.get('filename'):
                    source_info = f"（来源：{source['filename']}）"
                elif source.get('source'):
                    source_info = f"（来源：{source['source']}）"
            context_str += f"[资料 {i+1}]{source_info}: {chunk}\n"
        context_str += "\n---\n"

    # 添加图片处理结果到上下文
    if image_context:
        context_str += "以下是图片分析结果：\n\n"
        for item in image_context:
            context_str += item
        context_str += "\n---\n"
    return context_str
