import os
import dashscope   # 阿里云通义千问大模型API
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import chromadb  # 向量数据库，用于存储文档向量
from sentence_transformers import SentenceTransformer  # 文本向量化模型
import shutil
from typing import List

# ⚠️ 设置你的 API Key (建议从环境变量读取)
os.environ["DASHSCOPE_API_KEY"] = "sk-9de2fa96dcd240a882e4a461f1cea341"
dashscope.api_key = os.environ["DASHSCOPE_API_KEY"]

app = FastAPI()

# 允许跨域 (让 Vue 能访问)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 生产环境请指定具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化向量数据库 (本地持久化存储在当前目录 ./chroma_db)
client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection(name="docs_collection")

# 初始化 Embedding 模型 (使用本地的 all-MiniLM-L6-v2，免费且快) 将文本转换为 384 维的向量
# 第一次运行会自动下载模型，可能需要几分钟
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

class QueryRequest(BaseModel):
    query: str
    # 可选：携带历史上下文，这里简化为只传当前问题

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """接收文件，切片，向量化，存入数据库"""
    try:
        # 1. 保存文件到临时目录
        file_location = f"temp_{file.filename}"
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. 读取文件内容 (简单起见，这里只处理 .txt 文件)
        # 实际项目中需要引入 PyPDF2 或 python-docx 处理 PDF/Word
        if not file.filename.endswith(".txt"):
            raise HTTPException(status_code=400, detail="仅支持 txt 格式演示")

        with open(file_location, "r", encoding="utf-8") as f:
            content = f.read()

        # 3. 简单的文本切片 (按换行符或固定长度)
        # 生产环境需要用 langchain.text_splitter 进行更智能的切片
        chunks = [c.strip() for c in content.split("\n") if c.strip()]

        # 4. 向量化并存入 Chroma
        if chunks:
            texts = chunks
            # 生成本地向量 (免费，不消耗 Token)
            embeddings = embedding_model.encode(texts).tolist()
            ids = [f"doc_{i}" for i in range(len(texts))]

            collection.add(
                documents=texts,
                embeddings=embeddings,
                ids=ids
            )

        # 清理临时文件
        os.remove(file_location)

        return {"message": f"成功导入 {len(chunks)} 个文本片段"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def chat_with_docs(request: QueryRequest):
    """检索相关文档，并结合大模型回答"""
    query = request.query

    # 1. 将用户问题向量化
    query_embedding = embedding_model.encode([query]).tolist()[0]

    # 2. 在数据库中搜索最相似的 3 个片段
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=3
    )

    # 提取检索到的文档内容
    docs = results['documents'][0] if results['documents'] else []
    context_text = "\n".join(docs)

    if not context_text:
        return {"answer": "未在知识库中找到相关信息。"}

    # 3. 构造 Prompt (RAG 的核心)
    prompt = f"""
    你是一个基于知识库的智能助手。请严格根据以下【参考资料】回答用户的问题。
    如果资料中没有答案，请直接说“资料中未提及”，不要编造。

    【参考资料】：
    {context_text}

    【用户问题】：
    {query}
    """

    # 4. 调用通义千问 API
    try:
        response = dashscope.Generation.call(
            model='qwen-turbo',
            messages=[{'role': 'user', 'content': prompt}],
            result_format='message'
        )

        if response.status_code == 200:
            return {
                "answer": response.output.choices[0].message.content,
                "source_docs": docs # 返回来源，方便前端展示引用
            }
        else:
            raise HTTPException(status_code=500, detail=response.message)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # 启动服务，端口设为 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)