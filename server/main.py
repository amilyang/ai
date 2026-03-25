import os   # 操作系统相关，读取环境变量
import json  # 处理 JSON 数据格式
import time  # 时间相关，用于记录时间戳
import sqlite3  # 数据库操作模块，用于 SQLite 数据库
from typing import List, Optional   # 类型提示（让代码更规范）
from contextlib import asynccontextmanager
from unittest import result # 异步上下文管理器

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
            images TEXT DEFAULT '[]',  -- 新增：存储图片 URL 列表的 JSON 字符串
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

@app.post("/api/session")
async def create_session(req: SessionCreate):
    conn = await get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO sessions (title) VALUES (?)", (req.title,))
    session_id = c.lastrowid # 获取刚创建的 ID
    conn.commit()
    conn.close()
    return {"sessionId": session_id}
# --- 新增 API: 删除会话 ---
@app.delete("/api/session/{session_id}")
async def delete_session(session_id: int):
    conn = await get_db_connection()
    c = conn.cursor()
    # 先删除会话中的所有消息
    c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    # 再删除会话本身
    c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return {"message": "会话已删除"}
# --- 新增 API: 更新会话标题 ---
@app.put("/api/session/{session_id}")
async def update_session_title(session_id: int, title_data: dict):
    # title_data 期望格式: {"title": "新标题"}
    new_title = title_data.get('title')
    if not new_title:
        raise HTTPException(status_code=400, detail="Title is required")
    conn = await get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE sessions SET title = ? WHERE id = ?", (new_title, session_id))
    conn.commit()
    conn.close()
    return {"message": "会话标题已更新"}

@app.get("/api/history/{session_id}")
async def get_history(session_id: int):
    conn = await get_db_connection()
    c = conn.cursor()
    c.execute("SELECT role, content, images FROM messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    rows = c.fetchall()
    conn.close()

    print(f"查询会话 {session_id} 的历史记录: 共 {len(rows)} 条")
    result = []
    for row in rows:
        try:
            imgList = json.loads(row["images"]) if row["images"] else []
        except json.JSONDecodeError:
            imgList = []
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

    # 5. 组装 Payload - 支持多模态
    model_name = "qwen-turbo"
    payload_messages = [
        {"role": "system", "content": system_prompt},
        *history,
    ]

    # 预处理图片数据：直接使用原始 data URL（不提取base64）
    processed_images = []
    if req.images and len(req.images) > 0:
        for img_url in req.images:
            # 直接保留原始 data URL 格式
            processed_images.append(img_url)

    # 如果有图片，使用 Qwen-VL 模型
    if processed_images and len(processed_images) > 0:
        model_name = "qwen-vl-plus"
        # 构建多模态消息 - 使用 image_url 对象格式
        image_contents = []
        print(f"收到图片数量: {len(processed_images)}")
        for i, img_url in enumerate(processed_images):
            print(f"图片 {i+1}: {img_url[:50]}...")
            # 使用 image_url 对象格式
            image_contents.append({"image": img_url})
        # 添加文字描述
        image_contents.append({"text": req.message or "请描述这张图片"})
        print(f"最终 content: {image_contents}")
        payload_messages.append({"role": "user", "content": image_contents})
    else:
        payload_messages.append({"role": "user", "content": req.message})

    # 6. 定义流式生成器
    async def generate_stream():
        full_reply = ""
        try:
            # 如果有图片，使用 HTTP API 调用 Qwen-VL
            if processed_images and len(processed_images) > 0:
                # 直接使用已经构建好的 payload_messages（包含完整 data URL）
                mm_messages = payload_messages.copy()

                print(f"多模态消息图片数量: {len(processed_images)}, 第一张长度: {len(processed_images[0]) if processed_images else 0}")

                # 打印发送给 API 的完整请求体
                api_request = {
                    "model": model_name,
                    "input": {"messages": mm_messages},
                    "parameters": {"result_format": "message"}
                }
                print(f"API Request: {json.dumps(api_request, ensure_ascii=False)[:500]}...")

                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream(
                        "POST",
                        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                        headers={
                            "Authorization": f"Bearer {API_KEY}",
                            "Content-Type": "application/json",
                            "X-DashScope-SSE": "enable"
                        },
                        json={
                            "model": model_name,
                            "input": {"messages": mm_messages},
                            "parameters": {"result_format": "message"}
                        }
                    ) as response:
                        print(f"API response status: {response.status_code}")
                        if response.status_code != 200:
                            error_text = await response.aread()
                            print(f"API error: {response.status_code} - {error_text}")
                            yield f"data: {json.dumps({'error': f'API Error: {response.status_code}', 'details': error_text.decode()})}\n\n"
                            return

                        async for line in response.aiter_lines():
                            if line.startswith("data:"):
                                content_str = line[5:].strip()
                                if content_str and content_str != "[DONE]":
                                    try:
                                        data = json.loads(content_str)
                                        print(f"VL Response: {data}")

                                        # 修复：正确解析多模态响应
                                        output = data.get("output", {})
                                        choices = output.get("choices", [])
                                        if choices:
                                            choice = choices[0]
                                            message = choice.get("message", {})
                                            content_obj = message.get("content", [])

                                            # 多模态返回通常是列表，包含 image 和 text
                                            text_content = ""
                                            for item in content_obj:
                                                if item.get("text"):
                                                    text_content += item.get("text", "")

                                            if text_content:
                                                # 直接使用完整内容作为最新状态
                                                new_content = text_content[len(full_reply):]
                                                full_reply = text_content
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
            else:
                # 文本模式使用 HTTP 调用
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
                            "model": model_name,
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
                                        print(f"Text Response: {content}")
                                        if content:
                                            # 累加发送内容
                                            new_content = content[len(full_reply):]
                                            full_reply = content  # 直接使用完整内容作为最新状态
                                            print(f"Full reply: {full_reply}, New content: {new_content}")
                                            if new_content:
                                                yield f"data: {json.dumps({'content': new_content})}\n\n"
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
#--- 新增API：删除/修改某条特定消息（用于编辑功能）----
# 策略：当用户编辑某条消息时，我们删除该消息之后的所有消息（包括它自己）
# 然后插入新的用户消息，触发重新生成
@app.delete("/api/message/{message_id}")
async def delete_message(message_id: int):
    # 这是一个简化策略：找到这条消息的 session，删除这条消息及其之后的所有消息
    conn = await get_db_connection()
    c = conn.cursor()
   # 1. 找到这条消息的 session_id 和 created_at
    c.execute("SELECT session_id, created_at FROM messages WHERE id = ?", (message_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="消息不存在")
    session_id, created_at = row['session_id'], row['created_at']
    # 2. 删除该时间点之后的所有消息 (包含这条)
    c.execute("DELETE FROM messages WHERE session_id = ? AND created_at >= ?", (session_id, created_at))
    conn.commit()
    conn.close()
    return {"message": "消息已删除", "sessionId": session_id}

# 删除单条消息
@app.delete("/api/msg/{message_id}")
async def delete_single_message(message_id: int):
    conn = await get_db_connection()
    c = conn.cursor()
    try:
        # 获取要删除的消息信息
        c.execute("SELECT session_id, role, created_at FROM messages WHERE id = ?", (message_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="消息不存在")
        session_id, role, created_at = row
        # 2. 找到对应的消息
        if role == "user":
            # 删除用户消息时，删除对应的 AI 回复
            # 查找同一会话中，在该用户消息之后的第一条 assistant 消息
            c.execute('''
                SELECT id FROM messages
                WHERE session_id = ? AND role = 'assistant' AND created_at > ?
                ORDER BY created_at ASC LIMIT 1
            ''', (session_id, created_at))
            assistant_msg = c.fetchone()
            if assistant_msg:
                c.execute("DELETE FROM messages WHERE id = ?", (assistant_msg[0],))
        else:  # role == "assistant"
            # 删除 AI 回复时，删除对应的用户消息
            # 查找同一会话中，在该回复之前的最后一条 user 消息
            c.execute('''
                SELECT id FROM messages
                WHERE session_id = ? AND role = 'user' AND created_at < ?
                ORDER BY created_at DESC LIMIT 1
            ''', (session_id, created_at))
            user_msg = c.fetchone()
            if user_msg:
                c.execute("DELETE FROM messages WHERE id = ?", (user_msg[0],))

        # 3. 删除原始消息
        c.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
        conn.close()
        return {"message": "消息已删除"}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"删除消息失败: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 启动服务器: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
