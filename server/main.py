import os   # 操作系统相关，读取环境变量
import json  # 处理 JSON 数据格式
import time  # 时间相关，用于记录时间戳
import sqlite3  # 数据库操作模块，用于 SQLite 数据库
from typing import List, Optional   # 类型提示（让代码更规范）
from contextlib import asynccontextmanager # 异步上下文管理器
from pathlib import Path  # 处理文件路径

import dashscope # 阿里云大模型 SDK
from fastapi import FastAPI, HTTPException, Request, UploadFile, File  # Web 框架
from fastapi.middleware.cors import CORSMiddleware  # 跨域请求处理
from fastapi.responses import StreamingResponse  #流式响应
from pydantic import BaseModel # 数据验证
import httpx  # 异步 HTTP 客户端（发网络请求）
import dotenv # 读取 .env 环境变量文件
import chromadb  # 向量数据库（存 AI 理解的数据）
from dashscope import TextEmbedding  # 文本向量化工具

# 加载 .env 文件中的环境变量
dotenv.load_dotenv()

# --- 配置 ---
API_KEY = os.getenv("DASHSCOPE_API_KEY")  # 从环境变量读取 API 密钥
DB_PATH = "chat.db"  # 数据库文件名
CHROMA_PERSIST_DIR = "./chroma_db"  #向量数据库存储目录

# 设置 dashscope API Key
dashscope.api_key = API_KEY # 告诉 dashscope 你的密钥

if not API_KEY:
    raise ValueError("❌ 错误: 请在 .env 文件中设置 DASHSCOPE_API_KEY")

# --- 数据库初始化 (SQLite) ---
def init_sqlite():
    conn = sqlite3.connect(DB_PATH) # 连接数据库（没有就创建）
    c = conn.cursor() # 获取"指针"，用来执行 SQL 命令
     # 创建 sessions 表（存储对话会话）
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT DEFAULT '新对话',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
     # 创建 messages 表（存储消息）
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
    ''')
    conn.commit() # 提交保存
    conn.close() # 关闭连接
    print(f"✅ SQLite 数据库已初始化: {DB_PATH}")

# --- 向量数据库初始化 (ChromaDB) ---
def init_chroma():
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR) # 创建持久化客户端
    collection = client.get_or_create_collection(name="knowledge_base") # 获取/创建集合
    print(f"✅ ChromaDB 向量库已初始化: {CHROMA_PERSIST_DIR}")
    return collection

# 全局变量存储 Chroma 集合
chroma_collection = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_sqlite() # 启动时初始化数据库
    global chroma_collection
    chroma_collection = init_chroma() # 启动时初始化向量数据库
    yield  # 应用运行中...

app = FastAPI(lifespan=lifespan)  # 创建 FastAPI 应用

# --- 中间件 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境请替换为具体域名，如 ["https://your-domain.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 数据模型 ---
class ChatRequest(BaseModel):
    sessionId: int
    message: str

class SessionCreate(BaseModel):
    title: Optional[str] = "新对话"

# --- 辅助函数 ---

async def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row # 可以用 row["column"] 访问
    return conn

def get_embedding(text: str):
    """调用阿里云 DashScope 获取文本向量"""
    try:
        response = TextEmbedding.call(
            model="text-embedding-v2",  # 向量化模型
            input=text
        )
        if response.status_code == 200:
            return response.output['embeddings'][0]['embedding']
        else:
            print(f"❌ Embedding Error: {response.status_code} - {response.message}")
            return None
    except Exception as e:
        print(f"❌ Embedding Exception: {e}")
        return None

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50):
    """简单的文本切片逻辑"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap # 每次移动 chunk_size - overlap
    return chunks

# --- API 接口 ---

@app.post("/api/session")
async def create_session(req: SessionCreate):
    conn = await get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO sessions (title) VALUES (?)", (req.title,))
    session_id = c.lastrowid # 获取刚创建的 ID
    conn.commit()
    conn.close()
    return {"sessionId": session_id}

@app.get("/api/history/{session_id}")
async def get_history(session_id: int):
    conn = await get_db_connection()
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": row["role"], "content": row["content"]} for row in rows]

@app.post("/api/upload")
async def upload_knowledge(file: UploadFile = File(...)):
    """上传文件并构建向量索引"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # 只支持文本文件，PDF 需要额外的解析库 (如 pdfplumber)，这里简化处理
    if not file.filename.endswith(('.txt', '.md', '.json', '.csv')):
        # 实际生产中建议添加 PDF 解析逻辑
        pass

    try:
         # 1. 读取文件内容
        content = await file.read()
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File encoding error. Please use UTF-8 text files.")

    doc_id = f"doc_{int(time.time())}_{file.filename}"
     # 2. 切分文本
    chunks = chunk_text(text)

    if not chunks:
        raise HTTPException(status_code=400, detail="File content is empty")

    ids = []
    documents = []
    embeddings = []
    metadatas = []

    print(f"📚 正在处理 {len(chunks)} 个文本块...")

    # 3. 向量化每个小块并存入 ChromaDB
    for i, chunk in enumerate(chunks):
        emb = get_embedding(chunk)  # 变成向量
        if emb:
            ids.append(f"{doc_id}_chunk_{i}")
            documents.append(chunk)
            embeddings.append(emb)
            metadatas.append({"source": file.filename, "doc_id": doc_id})
        else:
            print(f"⚠️ 跳过第 {i} 块，向量化失败")

    if not embeddings:
        raise HTTPException(status_code=500, detail="Failed to generate embeddings")

    # 存入 ChromaDB
    chroma_collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas
    )

    return {"message": f"成功学习 {len(embeddings)} 个知识片段", "filename": file.filename}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.message or not req.sessionId:
        raise HTTPException(status_code=400, detail="Missing sessionId or message")

    conn = await get_db_connection()
    c = conn.cursor()

    # 1. 保存用户消息
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
              (req.sessionId, "user", req.message))
    conn.commit()

    # 2. RAG 检索：查找相关知识
    relevant_chunks = []
    try:
        query_emb = get_embedding(req.message)
        if query_emb:
            results = chroma_collection.query(
                query_embeddings=[query_emb],
                n_results=3
            )
            if results and results['documents']:
                relevant_chunks = results['documents'][0]
    except Exception as e:
        print(f"RAG Search Error: {e}")

    # 3. 构建上下文
    context_str = ""
    if relevant_chunks:
        context_str = "以下是相关的背景知识，请依据这些知识回答问题：\n\n"
        for i, chunk in enumerate(relevant_chunks):
            context_str += f"[资料 {i+1}]: {chunk}\n"
        context_str += "\n---\n"

    system_prompt = "你是一个乐于助人的 AI 助手。"
    if context_str:
        system_prompt += f"\n\n{context_str}\n如果背景知识与问题无关，你可以使用通用知识回答，但请优先参考背景资料。"

    # 4. 获取历史对话 (最近 10 条)
    c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT 10",
              (req.sessionId,))
    history_rows = c.fetchall()
    history = [{"role": r["role"], "content": r["content"]} for r in reversed(history_rows)]

    conn.close()

    # 5. 组装 Payload
    payload_messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": req.message}
    ]

    # 6. 定义流式生成器
    async def generate_stream():
        full_reply = ""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                    headers={
                        "Authorization": f"Bearer {API_KEY}",
                        "Content-Type": "application/json",
                        "X-DashScope-SSE": "enable"
                    },
                    json={
                        "model": "qwen-turbo",
                        "input": {"messages": payload_messages},
                        "parameters": {"result_format": "message"}
                    }
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        yield f"data: {json.dumps({'error': f'API Error: {response.status_code}'})}\n\n"
                        return

                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            content_str = line[5:].strip()
                            if content_str and content_str != "[DONE]":
                                try:
                                    data = json.loads(content_str)
                                    content = data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
                                    if content:
                                        full_reply = content
                                        yield f"data: {json.dumps({'content': content})}\n\n"
                                except json.JSONDecodeError:
                                    continue

                    # 7. 流结束后，保存 AI 回复到数据库
                    save_conn = await get_db_connection()
                    save_c = save_conn.cursor()
                    save_c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                                   (req.sessionId, "assistant", full_reply))
                    save_conn.commit()
                    save_conn.close()

                    yield "data: [DONE]\n\n"

        except Exception as e:
            print(f"Stream Error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 启动服务器: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)