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

# 提取图片中的文本（OCR）
import base64
from io import BytesIO
from PIL import Image
import pytesseract

# 文档处理库
import pdfplumber
from docx import Document

from rank_bm25 import BM25Okapi
import jieba

# 文件哈希计算
import hashlib

# 加载 .env 文件中的环境变量
dotenv.load_dotenv()

# --- 配置 ---
API_KEY = os.getenv("DASHSCOPE_API_KEY")  # 从环境变量读取 API 密钥
DB_PATH = "chat.db"  # 数据库文件名
CHROMA_PERSIST_DIR = "./chroma_db"  #向量数据库存储目录

# 模型配置
MODEL_NAME = os.getenv("MODEL_NAME", "qwen-turbo")  # 默认使用 qwen-turbo
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")  # 默认使用 text-embedding-v2

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

# --- 错误处理模块 ---
class AppError(Exception):
    """应用自定义异常基类"""
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class ValidationError(AppError):
    """验证错误"""
    def __init__(self, message: str):
        super().__init__("VALIDATION_ERROR", message, 400)

class DatabaseError(AppError):
    """数据库错误"""
    def __init__(self, message: str):
        super().__init__("DATABASE_ERROR", message, 500)

class ModelError(AppError):
    """模型错误"""
    def __init__(self, message: str):
        super().__init__("MODEL_ERROR", message, 500)

class FileError(AppError):
    """文件错误"""
    def __init__(self, message: str):
        super().__init__("FILE_ERROR", message, 400)

class NotFoundError(AppError):
    """资源不存在错误"""
    def __init__(self, message: str):
        super().__init__("NOT_FOUND", message, 404)

# 统一错误响应格式
def error_response(code: str, message: str, status_code: int = 400):
    """生成统一格式的错误响应"""
    return {"error": {"code": code, "message": message}}, status_code

# 流式错误响应
def streaming_error_response(code: str, message: str):
    """生成流式错误响应"""
    async def error_streamer():
        yield f"data: {json.dumps({'error': {'code': code, 'message': message}}, ensure_ascii=False)}\n\n"
        yield f"data: [DONE]\n\n"
    return StreamingResponse(error_streamer(), media_type="text/event-stream")

# --- 全局异常处理 ---
@app.exception_handler(AppError)
async def app_error_handler(request, exc: AppError):
    """处理应用自定义异常"""
    return error_response(exc.code, exc.message, exc.status_code)

@app.exception_handler(HTTPException)
async def http_error_handler(request, exc: HTTPException):
    """处理 HTTP 异常"""
    return error_response("HTTP_ERROR", exc.detail, exc.status_code)

@app.exception_handler(Exception)
async def general_error_handler(request, exc: Exception):
    """处理通用异常"""
    print(f"[ERROR] 未捕获的异常: {exc}")
    return error_response("INTERNAL_ERROR", "服务器内部错误，请稍后重试", 500)

# --- 数据库连接池 ---
import threading
from queue import Queue

class SQLiteConnectionPool:
    def __init__(self, db_path, max_connections=5):
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool = Queue(maxsize=max_connections)
        self.lock = threading.Lock()

        # 初始化连接池
        for _ in range(max_connections):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            self.pool.put(conn)

    def get_connection(self):
        """从连接池获取连接"""
        return self.pool.get()

    def return_connection(self, conn):
        """将连接归还到连接池"""
        if conn:
            self.pool.put(conn)

    def close_all(self):
        """关闭所有连接"""
        while not self.pool.empty():
            try:
                conn = self.pool.get_nowait()
                conn.close()
            except:
                pass

# 全局连接池实例
db_pool = None

def init_db_pool(db_path, max_connections=5):
    """初始化数据库连接池"""
    global db_pool
    db_pool = SQLiteConnectionPool(db_path, max_connections)

# --- 辅助函数 ---
async def get_db_connection():
    """从连接池获取数据库连接"""
    if not db_pool:
        init_db_pool(DB_PATH)
    return db_pool.get_connection()

async def return_db_connection(conn):
    """归还数据库连接到连接池"""
    if db_pool and conn:
        db_pool.return_connection(conn)

def get_embedding(text: str):
    """获取文本向量，只使用阿里云的文本向量化模型"""
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
    """批量获取文本向量"""
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
                    print(f"[INFO] 使用本地模型批量生成嵌入")
        except Exception as e:
            print(f"[ERROR] 批量向量化异常: {e}")
            # 回退到本地模型
            if local_embedding_model:
                batch_embeddings = local_embedding_model.encode(batch_texts).tolist()
                print(f"[INFO] 使用本地模型批量生成嵌入")

        # 对于失败的嵌入，使用单条处理
        for j, text in enumerate(batch_texts):
            if j < len(batch_embeddings) and batch_embeddings[j] is not None:
                embeddings.append(batch_embeddings[j])
            else:
                emb = get_embedding(text)
                embeddings.append(emb)

    return embeddings

def chunk_text(text: str, chunk_size: int = None, overlap: int = None):
    """智能文本分块逻辑，基于段落和句子分块"""
    # 使用配置值作为默认值
    if chunk_size is None:
        chunk_size = CHUNK_SIZE
    if overlap is None:
        overlap = CHUNK_OVERLAP

    chunks = []

    # 首先按段落分割
    paragraphs = text.split('\n\n')
    current_chunk = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        # 如果当前段落本身就小于chunk_size，直接添加到当前块
        if len(current_chunk) + len(paragraph) + 2 <= chunk_size:
            if current_chunk:
                current_chunk += '\n\n' + paragraph
            else:
                current_chunk = paragraph
        else:
            # 如果当前块不为空，先保存
            if current_chunk:
                chunks.append(current_chunk)
                # 计算重叠部分
                overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                current_chunk = overlap_text

            # 处理长段落，按句子分割
            sentences = []
            # 简单的句子分割（实际应用中可能需要更复杂的NLP处理）
            temp_sentence = ""
            for char in paragraph:
                temp_sentence += char
                if char in ['.', '。', '!', '！', '?', '？', ';', '；']:
                    sentences.append(temp_sentence)
                    temp_sentence = ""
            if temp_sentence:
                sentences.append(temp_sentence)

            # 组合句子到块中
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 <= chunk_size:
                    if current_chunk:
                        current_chunk += ' ' + sentence
                    else:
                        current_chunk = sentence
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                        overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                        current_chunk = overlap_text + ' ' + sentence
                    else:
                        # 单个句子就超过chunk_size，强制分割
                        start_idx = 0
                        while start_idx < len(sentence):
                            end_idx = start_idx + chunk_size
                            chunks.append(sentence[start_idx:end_idx])
                            start_idx += chunk_size - overlap
                        current_chunk = ""

    # 保存最后一个块
    if current_chunk:
        chunks.append(current_chunk)

    return chunks

# --- API 接口 ---
# --- 新增 API: 获取所有会话列表 ---
@app.get("/api/sessions")
async def list_sessions():
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        # 按时间倒序排列，最新的在最前
        c.execute("SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
        rows = c.fetchall()
        return [{"id": row["id"], "title": row["title"], "createdAt": row["created_at"]} for row in rows]
    finally:
        await return_db_connection(conn)

# --- 新增 API: 创建新会话 ---
@app.post("/api/session")
async def create_session(session: SessionCreate):
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO sessions (title) VALUES (?)", (session.title,))
        session_id = c.lastrowid
        conn.commit()
        return {"id": session_id, "title": session.title}
    finally:
        await return_db_connection(conn)

# --- 新增 API: 获取会话历史 ---
@app.get("/api/session/{session_id}")
async def get_session_history(session_id: int):
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT role, content, images FROM messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
        rows = c.fetchall()

        result = []
        for row in rows:
            imgList = json.loads(row["images"]) if row["images"] else []
            result.append({"role": row["role"], "content": row["content"], "images": imgList})
        return result
    finally:
        await return_db_connection(conn)

# --- 辅助函数：文件处理 ---
def process_pdf(file_content):
    """处理PDF文件，提取文本"""
    text = ""
    try:
        with pdfplumber.open(BytesIO(file_content)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text += f"[第{page_num}页]\n{page_text}\n\n"
        return text
    except Exception as e:
        print(f"[ERROR] PDF处理错误: {e}")
        raise

def process_word(file_content):
    """处理Word文件，提取文本"""
    text = ""
    try:
        doc = Document(BytesIO(file_content))
        for para in doc.paragraphs:
            if para.text:
                text += para.text + "\n"
        return text
    except Exception as e:
        print(f"[ERROR] Word处理错误: {e}")
        raise

def process_image(file_content):
    """处理图片文件，使用OCR提取文本"""
    text = ""
    try:
        img = Image.open(BytesIO(file_content))
        text = pytesseract.image_to_string(img, lang='chi_sim+eng')
        return text
    except Exception as e:
        print(f"[ERROR] 图片处理错误: {e}")
        raise

def calculate_file_hash(content):
    """计算文件哈希值，用于重复检测"""
    return hashlib.md5(content).hexdigest()

def generate_file_summary(text, max_length=200):
    """生成文件摘要"""
    # 简单的摘要生成：取前max_length个字符
    summary = text.strip()
    if len(summary) > max_length:
        summary = summary[:max_length] + "..."
    return summary

def check_file_security(text):
    """文件内容安全检查"""
    # 更智能的安全检查，区分恶意代码和合法内容
    # 只检查可能导致安全问题的具体模式
    unsafe_patterns = [
        # 危险的JavaScript执行
        "eval(", "exec(", "system(",
        # 危险的SQL操作
        "DROP TABLE", "DELETE FROM", "INSERT INTO"
    ]

    text_lower = text.lower()
    for pattern in unsafe_patterns:
        if pattern.lower() in text_lower:
            return False, f"文件包含不安全内容: {pattern}"

    # 检查文件长度
    if len(text) > 1000000:  # 1MB
        return False, "文件内容过长"

    return True, "文件内容安全"

# --- 上传文件 API ---
@app.post("/api/upload")
async def upload_knowledge(file: UploadFile = File(...)):
    """上传文件并构建向量索引"""
    start_time = time.time()

    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="未提供文件")

        # 检查文件大小（50MB限制）
        content = await file.read()
        file_size = len(content)
        max_file_size = 50 * 1024 * 1024  # 50MB
        if file_size > max_file_size:
            raise HTTPException(status_code=400, detail=f"文件过大。最大大小为 50MB，当前文件大小为 {file_size/1024/1024:.2f}MB")

        print(f"[FILE] 文件大小: {file_size} 字节")

        # 计算文件哈希值，用于重复检测
        file_hash = calculate_file_hash(content)
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
                    "filename": file.filename,
                    "success": True,
                    "duplicate": True
                }
        except Exception as e:
            print(f"[WARN] 检查重复文件时出错: {e}")
            # 继续处理，不阻止上传

        # 检查文件类型
        supported_extensions = ['.txt', '.md', '.json', '.csv', '.pdf', '.docx', '.jpg', '.jpeg', '.png', '.gif']
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in supported_extensions:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型。支持的文件类型: {', '.join(supported_extensions)}")

        # 根据文件类型处理
        text = ""
        try:
            if file.filename.endswith('.pdf'):
                print("[INFO] 处理PDF文件")
                text = process_pdf(content)
            elif file.filename.endswith('.docx'):
                print("[INFO] 处理Word文件")
                text = process_word(content)
            elif file.filename.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                print("[INFO] 处理图片文件")
                text = process_image(content)
            else:  # 文本文件
                print("[INFO] 处理文本文件")
                # 检测文件编码
                result = chardet.detect(content)
                encoding = result['encoding'] or 'utf-8'
                confidence = result['confidence']
                print(f"[FILE] 检测到文件编码: {encoding} (置信度: {confidence:.2f})")

                # 解码文件内容
                try:
                    text = content.decode(encoding)
                except UnicodeDecodeError as e:
                    print(f"[WARN] 使用 {encoding} 解码失败: {e}，尝试使用 utf-8 解码并忽略错误")
                    text = content.decode('utf-8', errors='replace')
        except Exception as e:
            print(f"[ERROR] 文件处理错误: {e}")
            raise HTTPException(status_code=400, detail=f"文件处理错误: {str(e)}")

        if not text.strip():
            raise HTTPException(status_code=400, detail="文件内容为空")

        # 文件内容安全检查
        is_safe, message = check_file_security(text)
        if not is_safe:
            raise HTTPException(status_code=400, detail=message)

        # 生成文件摘要
        file_summary = generate_file_summary(text)
        print(f"[OK] 成功提取文本，内容长度: {len(text)} 字符")
        print(f"[OK] 生成文件摘要: {file_summary}")

        doc_id = f"doc_{int(time.time())}_{file.filename}"
        # 切分文本
        chunks = chunk_text(text)

        if not chunks:
            raise HTTPException(status_code=400, detail="处理后文件内容为空")

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
                    "source": file.filename,
                    "doc_id": doc_id,
                    "file_hash": file_hash,
                    "chunk_index": i,
                    "timestamp": time.time(),
                    "file_summary": file_summary,
                    "file_size": file_size,
                    "file_type": file.content_type or "application/octet-stream"
                })
            else:
                print(f"[WARN] 跳过第 {i} 块，向量化失败")

        if not embeddings:
            # 如果无法生成嵌入，仍然返回成功，只是提示无法进行知识检索
            print("[WARN] 无法生成向量嵌入，文件上传成功但无法进行知识检索")
            return {"message": "文件上传成功，但无法生成向量嵌入，无法进行知识检索。请检查网络连接。", "filename": file.filename, "success": True}
        elif len(embeddings) < len(chunks):
            # 部分成功，仍然返回成功
            print(f"[WARN] 部分文本块向量化失败，成功 {len(embeddings)} 个，失败 {len(chunks) - len(embeddings)} 个")
            return {"message": f"文件上传成功，成功处理 {len(embeddings)} 个知识片段，部分片段处理失败。", "filename": file.filename, "success": True, "processed_chunks": len(embeddings), "total_chunks": len(chunks)}

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
            raise HTTPException(status_code=500, detail="存入向量数据库失败，请稍后重试")

        total_time = time.time() - start_time
        print(f"[INFO] 总处理时间: {total_time:.2f} 秒")

        return {
            "message": f"文件上传成功！成功处理 {len(embeddings)} 个知识片段。",
            "filename": file.filename,
            "success": True,
            "processed_chunks": len(embeddings),
            "total_chunks": len(chunks),
            "processing_time": f"{total_time:.2f} 秒"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 上传文件时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"上传文件时发生错误: {str(e)}")

# --- 新增 API: 获取文件列表 ---
@app.get("/api/files")
async def get_files():
    """获取已上传的文件列表"""
    try:
        # 从 ChromaDB 中获取所有文档的元数据
        all_docs = chroma_collection.get(
            include=['metadatas']
        )

        # 提取唯一的文件信息
        files = {}
        if all_docs and all_docs['metadatas']:
            for metadata in all_docs['metadatas']:
                if metadata and metadata.get('source'):
                    file_key = metadata['source']
                    if file_key not in files:
                        files[file_key] = {
                            'filename': metadata['source'],
                            'file_size': metadata.get('file_size', 0),
                            'file_type': metadata.get('file_type', 'unknown'),
                            'file_summary': metadata.get('file_summary', ''),
                            'upload_time': metadata.get('timestamp', 0)
                        }

        # 转换为列表并按上传时间排序
        file_list = list(files.values())
        file_list.sort(key=lambda x: x['upload_time'], reverse=True)

        return {"files": file_list, "total": len(file_list)}
    except Exception as e:
        print(f"[ERROR] 获取文件列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取文件列表失败")

# --- 新增 API: 搜索文件 ---
@app.get("/api/files/search")
async def search_files(query: str):
    """搜索文件"""
    try:
        # 从 ChromaDB 中搜索相关文档
        results = chroma_collection.query(
            query_texts=[query],
            n_results=20,
            include=['metadatas']
        )

        # 提取唯一的文件信息
        files = {}
        if results and results['metadatas']:
            for metadatas in results['metadatas']:
                for metadata in metadatas:
                    if metadata and metadata.get('source'):
                        file_key = metadata['source']
                        if file_key not in files:
                            files[file_key] = {
                                'filename': metadata['source'],
                                'file_size': metadata.get('file_size', 0),
                                'file_type': metadata.get('file_type', 'unknown'),
                                'file_summary': metadata.get('file_summary', ''),
                                'upload_time': metadata.get('timestamp', 0)
                            }

        # 转换为列表
        file_list = list(files.values())

        return {"files": file_list, "total": len(file_list)}
    except Exception as e:
        print(f"[ERROR] 搜索文件失败: {e}")
        raise HTTPException(status_code=500, detail="搜索文件失败")


# 模型配置
MODEL_CONFIGS = {
    "qwen-turbo": {
        "endpoint": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        "headers": {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable"
        },
        "payload_template": lambda messages: {
            "model": "qwen-turbo",
            "input": {"messages": messages},
            "parameters": {"result_format": "message"}
        },
        "response_parser": lambda data: data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
    },
    "qwen-vl-plus": {
        "endpoint": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        "headers": {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable"
        },
        "payload_template": lambda messages: {
            "model": "qwen-vl-plus",
            "input": {"messages": messages},
            "parameters": {"result_format": "message"}
        },
        "response_parser": lambda data: "".join([item.get("text", "") for item in data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", [])])
    }
}

# 辅助函数：处理图片内容
def process_images(images):
    """处理图片内容，提取文本"""
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

# 辅助函数：检索相关知识
def retrieve_relevant_knowledge(query):
    """检索相关知识，包括向量检索、BM25检索、合并去重和重排序"""
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

# 辅助函数：构建上下文
def build_context(relevant_chunks, chunk_sources, image_context):
    """构建对话上下文"""
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

# 辅助函数：获取历史对话
async def get_history_messages(session_id, max_history):
    """获取历史对话"""
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        c.execute(f"SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT {max_history}",
                  (session_id,))
        history_rows = c.fetchall()
        history = [{"role": r["role"], "content": r["content"]} for r in reversed(history_rows)]
        return history
    finally:
        await return_db_connection(conn)

# 辅助函数：构建消息
def build_messages(system_prompt, history, message, images):
    """构建消息，支持多模态"""
    if images and len(images) > 0:
        # 多模态消息格式
        user_content = [
            {"text": message}
        ]
        # 添加图片
        for img in images:
            user_content.append({"image": img})

        payload_messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_content}
        ]
        selected_model = "qwen-vl-plus"
    else:
        # 纯文本消息格式
        payload_messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": message}
        ]
        selected_model = "qwen-turbo"

    return payload_messages, selected_model

# 辅助函数：流式调用模型
async def generate_streaming_response(model_config, payload_messages, session_id):
    """流式调用模型并返回响应"""
    full_response = ""
    previous_content = ""
    try:
        # 检查 API_KEY
        if not API_KEY:
            yield f"data: {json.dumps({'error': {'code': 'API_KEY_MISSING', 'message': 'API_KEY 未设置，无法调用模型'}}, ensure_ascii=False)}\n\n"
            yield f"data: [DONE]\n\n"
            return

        # 检查模型配置
        if not model_config or "endpoint" not in model_config:
            yield f"data: {json.dumps({'error': {'code': 'MODEL_CONFIG_ERROR', 'message': '模型配置不正确，缺少endpoint'}}, ensure_ascii=False)}\n\n"
            yield f"data: [DONE]\n\n"
            return

        # 尝试调用模型
        try:
            # 构建模型参数
            payload = model_config["payload_template"](payload_messages)

            # 调用模型
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    model_config["endpoint"],
                    headers=model_config["headers"],
                    json=payload
                ) as response:
                    # 检查响应状态
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'error': {'code': 'MODEL_API_ERROR', 'message': f'模型API返回错误状态码: {response.status_code}'}}, ensure_ascii=False)}\n\n"
                        yield f"data: [DONE]\n\n"
                        return

                    # 处理响应
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            content_str = line[5:].strip()
                            if content_str and content_str != "[DONE]":
                                try:
                                    data = json.loads(content_str)

                                    # 检查是否是错误响应
                                    if 'code' in data and 'message' in data:
                                        error_message = f"模型API错误: {data['message']}"
                                        yield f"data: {json.dumps({'error': {'code': 'MODEL_API_ERROR', 'message': error_message}}, ensure_ascii=False)}\n\n"
                                    else:
                                        content = model_config["response_parser"](data)
                                        if content:
                                            full_response = content
                                            # 只发送新增的部分
                                            new_content = content[len(previous_content):]
                                            if new_content:
                                                yield f"data: {json.dumps({'content': new_content}, ensure_ascii=False)}\n\n"
                                                previous_content = content
                                except Exception as e:
                                    yield f"data: {json.dumps({'error': {'code': 'PARSING_ERROR', 'message': f'解析模型响应失败: {str(e)}'}}, ensure_ascii=False)}\n\n"
                        elif line == "[DONE]":
                            break
        except Exception as e:
            yield f"data: {json.dumps({'error': {'code': 'MODEL_ERROR', 'message': f'模型调用失败: {str(e)}'}}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': {'code': 'INTERNAL_ERROR', 'message': f'函数执行失败: {str(e)}'}}, ensure_ascii=False)}\n\n"
    finally:
        # 保存响应到数据库
        if full_response:
            try:
                conn = await get_db_connection()
                try:
                    c = conn.cursor()
                    c.execute("INSERT INTO messages (session_id, role, content, images) VALUES (?, ?, ?, ?)",
                              (session_id, "assistant", full_response, json.dumps([])))
                    conn.commit()
                finally:
                    await return_db_connection(conn)
            except Exception as db_error:
                print(f"[ERROR] 保存响应到数据库失败: {db_error}")
        # 结束响应
        yield f"data: [DONE]\n\n"

# 辅助函数：保存用户消息到数据库
async def save_user_message(session_id: int, message: str, images: list):
    """保存用户消息到数据库"""
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO messages (session_id, role, content, images) VALUES (?, ?, ?, ?)",
                  (session_id, "user", message, json.dumps(images or [])))
        conn.commit()
    finally:
        await return_db_connection(conn)

# 辅助函数：处理图片并返回错误响应（如果需要）
async def handle_images(images: list):
    """处理图片内容并返回错误响应（如果需要）"""
    image_context, is_valid = process_images(images)
    if not is_valid:
        return None, streaming_error_response("VALIDATION_ERROR", "图片格式无效，请上传有效的图片数据")
    return image_context, None

# 辅助函数：构建聊天上下文
async def build_chat_context(session_id: int, message: str, image_context: list):
    """构建聊天上下文"""
    # 检索相关知识
    relevant_chunks, chunk_sources = retrieve_relevant_knowledge(message)
    # 构建上下文
    context_str = build_context(relevant_chunks, chunk_sources, image_context)
    # 获取历史对话
    history = await get_history_messages(session_id, MAX_HISTORY_MESSAGES)
    return context_str, history

# 辅助函数：准备模型参数
async def prepare_model_parameters(context_str: str, history: list, message: str, images: list):
    """准备模型参数"""
    # 组装消息
    system_prompt = "你是一个乐于助人的 AI 助手。"
    if context_str:
        system_prompt += f"\n\n{context_str}\n如果背景知识与问题无关，你可以使用通用知识回答，但请优先参考背景资料。"

    payload_messages, selected_model = build_messages(system_prompt, history, message, images)

    # 获取模型配置
    model_config = MODEL_CONFIGS.get(selected_model)
    if not model_config:
        # 模型配置不存在，使用默认模型
        model_config = MODEL_CONFIGS["qwen-turbo"]

    return model_config, payload_messages

# 辅助函数：生成流式响应
async def generate_chat_response(model_config, payload_messages, session_id: int):
    """生成流式响应"""
    try:
        # 调用模型生成响应
        streamer = generate_streaming_response(model_config, payload_messages, session_id)
        response = StreamingResponse(streamer, media_type="text/event-stream")
        return response
    except Exception as e:
        # 返回一个错误响应
        return streaming_error_response("MODEL_ERROR", f"创建流式响应失败: {str(e)}")

# --- 新增 API: 与 AI 交互 ---
@app.post("/api/chat")
async def chat(req: ChatRequest):
    """处理聊天请求"""
    # 1. 保存用户消息到数据库
    await save_user_message(req.sessionId, req.message, req.images)

    # 2. 处理图片内容
    image_context, error_response = await handle_images(req.images)
    if error_response:
        return error_response

    # 3. 构建聊天上下文
    context_str, history = await build_chat_context(req.sessionId, req.message, image_context)

    # 4. 准备模型参数
    model_config, payload_messages = await prepare_model_parameters(context_str, history, req.message, req.images)

    # 5. 生成流式响应
    return await generate_chat_response(model_config, payload_messages, req.sessionId)


# --- 新增 API: 删除会话 ---
@app.delete("/api/session/{session_id}")
async def delete_session(session_id: int):
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        # 先删除会话的所有消息
        c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        # 再删除会话本身
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return {"message": "会话已删除"}
    finally:
        await return_db_connection(conn)

# --- 新增 API: 删除单条消息 ---
@app.delete("/api/msg/{message_id}")
async def delete_single_message(message_id: int):
    conn = await get_db_connection()
    try:
        c = conn.cursor()

        # 获取要删除的消息信息
        c.execute("SELECT session_id, role, created_at FROM messages WHERE id = ?", (message_id,))
        message = c.fetchone()

        if not message:
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
        return {"message": "消息及相关消息已删除"}
    finally:
        await return_db_connection(conn)

# --- 系统提示词 ---
system_prompt = "你是一个智能助手，基于用户提供的知识和对话历史进行回答。请保持回答友好、准确，并且只基于提供的信息进行回答。"

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # 修改端口为 8000
    print(f"[SERVER] 启动服务器: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
