from typing import List
from config import EMBEDDING_MODEL
import dashscope
from dashscope import TextEmbedding

# 全局变量，存储本地嵌入模型（如果需要）
local_embedding_model = None

def get_embedding(text: str):
    """获取文本向量，只使用阿里云的文本向量化模型
    
    Args:
        text: 要向量化的文本
    
    Returns:
        list: 文本向量
    """
    # 尝试使用阿里云 API
    try:
        response = TextEmbedding.call(
            model=EMBEDDING_MODEL,  # 使用配置的向量化模型
            input=text
        )
        if response.status_code == 200:
            return response.output['embeddings'][0]['embedding']
        else:
            print(f"[ERROR] Embedding Error: {response.status_code} - {response.message}")
            # 尝试使用其他模型
            print("[INFO] 尝试使用 text-embedding-v1 模型...")
            try:
                response_v1 = TextEmbedding.call(
                    model="text-embedding-v1",  # 尝试使用 v1 模型
                    input=text
                )
                if response_v1.status_code == 200:
                    return response_v1.output['embeddings'][0]['embedding']
                else:
                    print(f"[ERROR] Embedding v1 Error: {response_v1.status_code} - {response_v1.message}")
                    return None
            except Exception as e:
                print(f"[ERROR] Embedding v1 Exception: {e}")
                return None
    except Exception as e:
        print(f"[ERROR] Embedding Exception: {e}")
        return None

def get_batch_embeddings(texts: List[str], batch_size: int = 8):
    """批量获取文本向量
    
    Args:
        texts: 要向量化的文本列表
        batch_size: 批处理大小
    
    Returns:
        list: 文本向量列表
    """
    embeddings = []
    # 分批处理
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i+batch_size]
        batch_embeddings = []

        # 尝试使用阿里云 API 批量处理
        try:
            response = TextEmbedding.call(
                model=EMBEDDING_MODEL,
                input=batch_texts
            )
            if response.status_code == 200:
                batch_embeddings = [emb['embedding'] for emb in response.output['embeddings']]
                print(f"[INFO] 批量向量化成功: {len(batch_embeddings)} 个文本")
            else:
                print(f"[ERROR] 批量向量化失败: {response.status_code} - {response.message}")
                # 回退到本地模型
                if local_embedding_model:
                    batch_embeddings = local_embedding_model.encode(batch_texts).tolist()
                    print("[INFO] 使用本地模型批量生成嵌入")
        except Exception as e:
            print(f"[ERROR] 批量向量化异常: {e}")
            # 回退到本地模型
            if local_embedding_model:
                batch_embeddings = local_embedding_model.encode(batch_texts).tolist()
                print("[INFO] 使用本地模型批量生成嵌入")

        # 对于失败的嵌入，使用单条处理
        for j, text in enumerate(batch_texts):
            if j < len(batch_embeddings) and batch_embeddings[j] is not None:
                embeddings.append(batch_embeddings[j])
            else:
                emb = get_embedding(text)
                embeddings.append(emb)

    return embeddings
