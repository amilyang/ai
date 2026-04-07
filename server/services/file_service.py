import time
import os
from io import BytesIO
from typing import Optional
from utils.file import process_pdf, process_word, process_image, calculate_file_hash, generate_file_summary, check_file_security
from utils.embedding import get_batch_embeddings
from utils.text import chunk_text
from config import MAX_RELEVANT_CHUNKS

async def process_uploaded_file(file_content: bytes, filename: str, chroma_collection):
    """处理上传的文件并构建向量索引
    
    Args:
        file_content: 文件内容
        filename: 文件名
        chroma_collection: ChromaDB集合
    
    Returns:
        dict: 处理结果
    """
    start_time = time.time()

    try:
        if not filename:
            return {"message": "未提供文件", "filename": "", "success": False}

        # 检查文件大小（50MB限制）
        file_size = len(file_content)
        max_file_size = 50 * 1024 * 1024  # 50MB
        if file_size > max_file_size:
            return {"message": f"文件过大。最大大小为 50MB，当前文件大小为 {file_size/1024/1024:.2f}MB", "filename": filename, "success": False}

        print(f"[FILE] 文件大小: {file_size} 字节")

        # 计算文件哈希值，用于重复检测
        file_hash = calculate_file_hash(file_content)
        print(f"[FILE] 文件哈希: {file_hash}")

        # 检查是否重复上传
        try:
            # 搜索具有相同文件哈希的文档
            existing_docs = chroma_collection.get(
                where={"file_hash": file_hash}
            )
            if existing_docs and existing_docs['ids']:
                print(f"[INFO] 检测到重复文件，已存在 {len(existing_docs['ids'])} 个相关文档")
                return {
                    "message": "文件已存在，无需重复上传。",
                    "filename": filename,
                    "success": True,
                    "duplicate": True
                }
        except Exception as e:
            print(f"[WARN] 检查重复文件时出错: {e}")
            # 继续处理，不阻止上传

        # 检查文件类型
        supported_extensions = ['.txt', '.md', '.json', '.csv', '.pdf', '.docx', '.jpg', '.jpeg', '.png', '.gif']
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in supported_extensions:
            return {"message": f"不支持的文件类型。支持的文件类型: {', '.join(supported_extensions)}", "filename": filename, "success": False}

        # 根据文件类型处理
        text = ""
        try:
            if filename.endswith('.pdf'):
                print("[INFO] 处理PDF文件")
                text = process_pdf(file_content)
            elif filename.endswith('.docx'):
                print("[INFO] 处理Word文件")
                text = process_word(file_content)
            elif filename.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                print("[INFO] 处理图片文件")
                text = process_image(file_content)
            else:  # 文本文件
                print("[INFO] 处理文本文件")
                # 检测文件编码
                import chardet
                result = chardet.detect(file_content)
                encoding = result['encoding'] or 'utf-8'
                confidence = result['confidence']
                print(f"[FILE] 检测到文件编码: {encoding} (置信度: {confidence:.2f})")

                # 解码文件内容
                try:
                    text = file_content.decode(encoding)
                except UnicodeDecodeError as e:
                    print(f"[WARN] 使用 {encoding} 解码失败: {e}，尝试使用 utf-8 解码并忽略错误")
                    text = file_content.decode('utf-8', errors='replace')
        except Exception as e:
            print(f"[ERROR] 文件处理错误: {e}")
            return {"message": f"文件处理错误: {str(e)}", "filename": filename, "success": False}

        if not text.strip():
            return {"message": "文件内容为空", "filename": filename, "success": False}

        # 文件内容安全检查
        is_safe, message = check_file_security(text)
        if not is_safe:
            return {"message": message, "filename": filename, "success": False}

        # 生成文件摘要
        file_summary = generate_file_summary(text)
        print(f"[OK] 成功提取文本，内容长度: {len(text)} 字符")
        print(f"[OK] 生成文件摘要: {file_summary}")

        doc_id = f"doc_{int(time.time())}_{filename}"
        # 切分文本
        chunks = chunk_text(text)

        if not chunks:
            return {"message": "处理后文件内容为空", "filename": filename, "success": False}

        ids = []
        documents = []
        embeddings = []
        metadatas = []

        print(f"[INFO] 正在处理 {len(chunks)} 个文本块...")

        # 批量向量化文本块并存入 ChromaDB
        max_time = 120  # 最大处理时间，单位秒

        # 批量获取嵌入
        batch_embeddings = get_batch_embeddings(chunks)

        # 处理嵌入结果
        for i, (chunk, emb) in enumerate(zip(chunks, batch_embeddings)):
            # 检查是否超时
            if time.time() - start_time > max_time:
                print("[WARN] 文件处理超时，停止向量化")
                break

            if emb:
                ids.append(f"{doc_id}_chunk_{i}")
                documents.append(chunk)
                embeddings.append(emb)
                metadatas.append({
                    "source": filename,
                    "doc_id": doc_id,
                    "file_hash": file_hash,
                    "chunk_index": i,
                    "timestamp": time.time(),
                    "file_summary": file_summary,
                    "file_size": file_size,
                    "file_type": "application/octet-stream"  # 简化处理
                })
            else:
                print(f"[WARN] 跳过第 {i} 块，向量化失败")

        if not embeddings:
            # 如果无法生成嵌入，仍然返回成功，只是提示无法进行知识检索
            print("[WARN] 无法生成向量嵌入，文件上传成功但无法进行知识检索")
            return {"message": "文件上传成功，但无法生成向量嵌入，无法进行知识检索。请检查网络连接。", "filename": filename, "success": True}
        elif len(embeddings) < len(chunks):
            # 部分成功，仍然返回成功
            print(f"[WARN] 部分文本块向量化失败，成功 {len(embeddings)} 个，失败 {len(chunks) - len(embeddings)} 个")
            return {"message": f"文件上传成功，成功处理 {len(embeddings)} 个知识片段，部分片段处理失败。", "filename": filename, "success": True, "processed_chunks": len(embeddings), "total_chunks": len(chunks)}

        # 存入 ChromaDB
        try:
            chroma_collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )
            print(f"[OK] 成功存入 {len(embeddings)} 个文本块到向量数据库")
        except Exception as e:
            print(f"[ERROR] 存入向量数据库失败: {e}")
            return {"message": "存入向量数据库失败，请稍后重试", "filename": filename, "success": False}

        total_time = time.time() - start_time
        print(f"[INFO] 总处理时间: {total_time:.2f} 秒")

        return {
            "message": f"文件上传成功！成功处理 {len(embeddings)} 个知识片段。",
            "filename": filename,
            "success": True,
            "processed_chunks": len(embeddings),
            "total_chunks": len(chunks),
            "processing_time": f"{total_time:.2f} 秒"
        }
    except Exception as e:
        print(f"[ERROR] 上传文件时发生错误: {e}")
        return {"message": f"上传文件时发生错误: {str(e)}", "filename": filename, "success": False}
