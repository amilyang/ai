import os   # 操作系统相关，读取环境变量
import json  # 处理 JSON 数据格式
import time  # 时间相关，用于记录时间戳
import sqlite3  # 数据库操作模块，用于 SQLite 数据库
from typing import List, Optional   # 类型提示（让代码更规范）
from contextlib import asynccontextmanager

import dashscope # 阿里云大模型 SDK
from fastapi import FastAPI, HTTPException, UploadFile, File  # Web 框架
from fastapi.middleware.cors import CORSMiddleware  # 跨域请求处理
from fastapi.responses import StreamingResponse  #流式响应
from pydantic import BaseModel # 数据验证
import httpx  # 异步 HTTP 客户端（发网络请求）
import dotenv # 读取 .env 环境变量文件
import chromadb  # 向量数据库（存 AI 理解的数据）
from dashscope import TextEmbedding  # 文本向量化工具
from dashscope import Generation  # 文本生成工具
import chardet  # 文件编码检测库

# 尝试导入 sentence-transformers 作为本地嵌入备选
local_embedding_model = None
local_embedding_available = False
try:
    from sentence_transformers import SentenceTransformer
    local_embedding_available = True
    print("[OK] 本地嵌入模型库已就绪")
except Exception as e:
    print(f"[WARN] 本地嵌入模型库不可用: {e}")

# 延迟加载本地嵌入模型
def load_local_embedding_model():
    global local_embedding_model
    if local_embedding_available and local_embedding_model is None:
        try:
            local_embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            print("[OK] 本地嵌入模型已加载: all-MiniLM-L6-v2")
            return local_embedding_model
        except Exception as e:
            print(f"[WARN] 无法加载本地嵌入模型: {e}")
            return None
    return local_embedding_model

# 加载 .env 文件中的环境变量
dotenv.load_dotenv()

# --- 配置 ---
API_KEY = os.getenv("DASHSCOPE_API_KEY")  # 从环境变量读取 API 密钥
DB_PATH = "chat.db"  # 数据库文件名
CHROMA_PERSIST_DIR = "./chroma_db"  #向量数据库存储目录

# 模型配置
MODEL_NAME = os.getenv("MODEL_NAME", "qwen-turbo")  # 默认使用 qwen-turbo
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v2")  # 默认使用 text-embedding-v2

# 文本处理配置
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 500))  # 文本分块大小
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 50))  # 文本分块重叠大小
MAX_RELEVANT_CHUNKS = int(os.getenv("MAX_RELEVANT_CHUNKS", 3))  # 最大相关知识片段数
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", 10))  # 最大历史消息数

# 设置 dashscope API Key
dashscope.api_key = API_KEY # 告诉 dashscope 你的密钥

if not API_KEY:
    raise ValueError("错误: 请在 .env 文件中设置 DASHSCOPE_API_KEY")

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
            images TEXT DEFAULT '[]',  -- 新增：存储图片 URL 列表的 JSON 字符串
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
    ''')
    conn.commit() # 提交保存
    conn.close() # 关闭连接
    print(f"[DB] SQLite 数据库已初始化: {DB_PATH}")

# --- 向量数据库初始化 (ChromaDB) ---
def init_chroma():
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR) # 创建持久化客户端
    collection = client.get_or_create_collection(name="knowledge_base") # 获取/创建集合
    print(f"[DB] ChromaDB 向量库已初始化: {CHROMA_PERSIST_DIR}")
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
    message: str = ""
    images: Optional[List[str]] = None

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

def chunk_text(text: str, chunk_size: int = None, overlap: int = None):
    """简单的文本切片逻辑"""
    # 使用配置值作为默认值
    if chunk_size is None:
        chunk_size = CHUNK_SIZE
    if overlap is None:
        overlap = CHUNK_OVERLAP

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
# --- 新增 API: 获取所有会话列表 ---
@app.get("/api/sessions")
async def list_sessions():
    conn = await get_db_connection()
    c = conn.cursor()
    # 按时间倒序排列，最新的在最前
    c.execute("SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [{"id": row["id"], "title": row["title"], "createdAt": row["created_at"]} for row in rows]

# --- 新增 API: 创建新会话 ---
@app.post("/api/sessions")
async def create_session(session: SessionCreate):
    conn = await get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO sessions (title) VALUES (?)", (session.title,))
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"id": session_id, "title": session.title}

# --- 新增 API: 获取会话历史 ---
@app.get("/api/sessions/{session_id}")
async def get_session_history(session_id: int):
    conn = await get_db_connection()
    c = conn.cursor()
    c.execute("SELECT role, content, images FROM messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    rows = c.fetchall()
    conn.close()

    result = []
    for row in rows:
        imgList = json.loads(row["images"]) if row["images"] else []
        result.append({"role": row["role"], "content": row["content"], "images": imgList})
    return result

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
        print(f"[FILE] 文件大小: {len(content)} 字节")

        # 2. 检测文件编码
        result = chardet.detect(content)
        encoding = result['encoding'] or 'utf-8'  # 如果检测失败，默认使用 utf-8
        confidence = result['confidence']
        print(f"[FILE] 检测到文件编码: {encoding} (置信度: {confidence:.2f})")

        # 3. 解码文件内容
        try:
            text = content.decode(encoding)
            print(f"[OK] 成功解码文件，内容长度: {len(text)} 字符")
        except UnicodeDecodeError as e:
            # 如果解码失败，尝试使用 utf-8 解码并忽略错误
            print(f"[WARN] 使用 {encoding} 解码失败: {e}，尝试使用 utf-8 解码并忽略错误")
            text = content.decode('utf-8', errors='replace')
            print(f"[OK] 使用 utf-8 解码成功，内容长度: {len(text)} 字符")
    except Exception as e:
        print(f"[ERROR] 文件读取错误: {e}")
        raise HTTPException(status_code=400, detail="File reading error. Please check the file format.")

    doc_id = f"doc_{int(time.time())}_{file.filename}"
    # 2. 切分文本
    chunks = chunk_text(text)

    if not chunks:
        raise HTTPException(status_code=400, detail="File content is empty")

    ids = []
    documents = []
    embeddings = []
    metadatas = []

    print(f"[INFO] 正在处理 {len(chunks)} 个文本块...")

    # 3. 向量化每个小块并存入 ChromaDB
    for i, chunk in enumerate(chunks):
        emb = get_embedding(chunk)  # 变成向量
        if emb:
            ids.append(f"{doc_id}_chunk_{i}")
            documents.append(chunk)
            embeddings.append(emb)
            metadatas.append({"source": file.filename, "doc_id": doc_id})
        else:
            print(f"[WARN] 跳过第 {i} 块，向量化失败")

    if not embeddings:
        # 如果无法生成嵌入，仍然返回成功，只是提示无法进行知识检索
        print("[WARN] 无法生成向量嵌入，文件上传成功但无法进行知识检索")
        return {"message": "文件上传成功，但无法生成向量嵌入，无法进行知识检索。请检查API密钥或网络连接。", "filename": file.filename}

    # 存入 ChromaDB
    chroma_collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas
    )

    return {"message": f"成功学习 {len(embeddings)} 个知识片段", "filename": file.filename}

# --- 新增 API: 与 AI 交互 ---
@app.post("/api/chat")
async def chat(req: ChatRequest):
    # message 为必填项
    if not req.sessionId or not req.message:
        raise HTTPException(status_code=400, detail="Missing sessionId or message")

    conn = await get_db_connection()
    c = conn.cursor()

    # 将图片列表序列化为 JSON 字符串，如果没有图片则存 '[]'
    images_json = json.dumps(req.images) if req.images else '[]'

    # 1. 保存用户消息
    c.execute("INSERT INTO messages (session_id, role, content, images) VALUES (?, ?, ?, ?)",
              (req.sessionId, "user", req.message, images_json))
    conn.commit()

    # 2. RAG 检索：查找相关知识（仅在有文字消息时进行）
    relevant_chunks = []
    if req.message and req.message.strip():
        try:
            query_emb = get_embedding(req.message)
            if query_emb:
                results = chroma_collection.query(
                    query_embeddings=[query_emb],
                    n_results=MAX_RELEVANT_CHUNKS
                )
                if results and results['documents']:
                    relevant_chunks = results['documents'][0]
        except Exception as e:
            print(f"RAG Search Error: {e}")

    # 3. 构建上下文
    context_str = ""
    if relevant_chunks:
        context_str = "\n".join([f"[知识片段 {i+1}]\n{chunk}\n" for i, chunk in enumerate(relevant_chunks)])
        print(f"[INFO] 找到 {len(relevant_chunks)} 个相关知识片段")
    else:
        print("[INFO] 未找到相关知识")

    # 4. 获取历史对话
    c.execute(f"SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT {MAX_HISTORY_MESSAGES}",
              (req.sessionId,))
    history_rows = c.fetchall()
    history = [{"role": r["role"], "content": r["content"]} for r in reversed(history_rows)]

    conn.close()

    # 5. 组装 Payload - 支持多模态
    model_name = MODEL_NAME
    payload_messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": req.message}
    ]

    # 6. 流式调用模型
    async def generate_stream():
        full_reply = ""
        try:
            # 流式调用模型
            response = Generation.call(
                model=model_name,
                messages=payload_messages,
                result_format="message",
                stream=True
            )

            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    content_str = line[5:].strip()
                    if content_str and content_str != "[DONE]":
                        try:
                            data = json.loads(content_str)
                            content = data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
                            print(f"Text Response: {content}")
                            if content:
                                # 累加发送内容
                                new_content = content[len(full_reply):]
                                full_reply = content
                                if new_content:
                                    yield f"data: {json.dumps({'content': new_content})}\n\n"
                        except json.JSONDecodeError:
                            print(f"JSON decode error on line: {line}")
                            continue
                        except Exception as e:
                            print(f"Error processing response line: {e}")
                            continue
                elif line == "[DONE]":
                    break
        except Exception as e:
            print(f"Stream Error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # 保存 AI 回复到数据库
            if full_reply:
                try:
                    conn = await get_db_connection()
                    c = conn.cursor()
                    c.execute("INSERT INTO messages (session_id, role, content, images) VALUES (?, ?, ?, ?)",
                              (req.sessionId, "assistant", full_reply, '[]'))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"Error saving assistant message: {e}")

    # 7. 流式返回响应
    return StreamingResponse(generate_stream(), media_type="text/event-stream")

# --- 新增 API: 删除会话 ---
@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int):
    conn = await get_db_connection()
    c = conn.cursor()
    # 先删除会话的所有消息
    c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    # 再删除会话本身
    c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"message": "会话已删除"}

# --- 新增 API: 删除单条消息 ---
@app.delete("/api/msg/{message_id}")
async def delete_single_message(message_id: int):
    conn = await get_db_connection()
    c = conn.cursor()

    # 获取要删除的消息信息
    c.execute("SELECT session_id, role, created_at FROM messages WHERE id = ?", (message_id,))
    message = c.fetchone()

    if not message:
        conn.close()
        raise HTTPException(status_code=404, detail="消息不存在")

    session_id = message["session_id"]
    role = message["role"]
    created_at = message["created_at"]

    # 删除选中的消息
    c.execute("DELETE FROM messages WHERE id = ?", (message_id,))

    # 根据角色删除相关的消息对
    if role == "user":
        # 如果删除的是用户消息，查找并删除后续的AI回复
        c.execute("""
            DELETE FROM messages
            WHERE session_id = ? AND role = 'assistant' AND created_at > ?
            ORDER BY created_at ASC LIMIT 1
        """, (session_id, created_at))
    elif role == "assistant":
        # 如果删除的是AI回复，查找并删除之前的用户消息
        c.execute("""
            DELETE FROM messages
            WHERE session_id = ? AND role = 'user' AND created_at < ?
            ORDER BY created_at DESC LIMIT 1
        """, (session_id, created_at))

    conn.commit()
    conn.close()
    return {"message": "消息及相关消息已删除"}

# --- 系统提示词 ---
system_prompt = "你是一个智能助手，基于用户提供的知识和对话历史进行回答。请保持回答友好、准确，并且只基于提供的信息进行回答。"

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # 修改端口为 8000
    print(f"[SERVER] 启动服务器: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
