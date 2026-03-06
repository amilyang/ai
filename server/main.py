# server/main.py
import os
import json
import asyncio
import sqlite3
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import dotenv

# 加载环境变量
dotenv.load_dotenv()

API_KEY = os.getenv("DASHSCOPE_API_KEY")
DB_PATH = "chat.db"

if not API_KEY:
    raise ValueError("⚠️ 致命错误：未找到 DASHSCOPE_API_KEY 环境变量！")

# --- 数据库初始化 (同步方式即可，因为只在启动时运行) ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT DEFAULT '新对话',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
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
    conn.commit()
    conn.close()
    print(f"✅ 数据库已初始化: {DB_PATH}")

# 在应用启动时运行
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# 允许跨域 (前端通常在 localhost:5173 或 3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议指定具体域名
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

# --- 辅助函数：异步获取数据库连接 ---
async def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 让结果可以通过列名访问
    return conn

# --- API 接口 ---

# 1. 创建会话
@app.post("/api/session")
async def create_session(req: SessionCreate):
    print("🚀 [DEBUG] 收到创建会话请求")  # 1. 确认请求进来了
    api_key = os.getenv("DASHSCOPE_API_KEY")
    print(f"🔑 [DEBUG] API Key 存在吗？{bool(api_key)}") # 2. 确认 Key 读到了
    if not api_key:
        print("❌ [ERROR] API KEY 缺失！")
        return {"error": "Server config error"}, 500
    conn = await get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO sessions (title) VALUES (?)", (req.title,))
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"sessionId": session_id}

# 2. 获取历史消息
@app.get("/api/history/{session_id}")
async def get_history(session_id: int):
    conn = await get_db_connection()
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": row["role"], "content": row["content"]} for row in rows]

# 3. 聊天接口 (核心：流式处理)
@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.message or not req.sessionId:
        raise HTTPException(status_code=400, detail="缺少参数")

    conn = await get_db_connection()
    c = conn.cursor()

    # A. 保存用户消息
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
              (req.sessionId, "user", req.message))
    conn.commit()

    # B. 获取历史记录 (最近 10 条)
    c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT 10",
              (req.sessionId,))
    history_rows = c.fetchall()
    # 反转回正序
    history = [{"role": r["role"], "content": r["content"]} for r in reversed(history_rows)]

    conn.close()

    # 构建发送给大模型的 messages
    payload_messages = [
        {"role": "system", "content": "你是一个乐于助人的 AI 助手。"},
        *history,
        {"role": "user", "content": req.message}
    ]

    # 定义生成器函数用于 StreamingResponse
    async def generate_stream():
        full_reply = ""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # 注意：httpx 的 stream 方法
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
                                        full_reply += content
                                        # 发送 SSE 格式
                                        yield f"data: {json.dumps({'content': content})}\n\n"
                                except json.JSONDecodeError:
                                    continue

                    # 流结束后，保存完整回复到数据库
                    # 注意：这里需要重新获取连接，因为上面的 async with 已经关闭了之前的逻辑作用域（虽然conn对象还在，但为了安全起见）
                    # 实际上 sqlite3 连接不是 async 的，直接在 async 函数里用没问题，只要不阻塞太久。
                    # 保存操作很快，直接做。
                    save_conn = await get_db_connection()
                    save_c = save_conn.cursor()
                    save_c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                                   (req.sessionId, "assistant", full_reply))
                    save_conn.commit()
                    save_conn.close()

                    yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate_stream(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))