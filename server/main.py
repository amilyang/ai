from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware  # 跨域请求处理
from fastapi.responses import StreamingResponse  #流式响应
import time

from config import DB_PATH, PORT
from database import init_sqlite, init_db_pool
from errors import setup_exception_handlers
from api.chat import router as chat_router
from api.files import router as files_router
from api.sessions import router as sessions_router
from dependencies import chroma_collection

# 初始化数据库
init_sqlite(DB_PATH)

# 初始化数据库连接池
init_db_pool(DB_PATH)

# 创建 FastAPI 应用实例
app = FastAPI()

# 配置 CORS（跨域资源共享）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有 HTTP 头
)

# 设置全局异常处理
setup_exception_handlers(app)

# 健康检查端点
@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    try:
        # 检查数据库连接
        from database import get_db_connection, return_db_connection
        conn = await get_db_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT 1")
            c.fetchone()
            db_status = "healthy"
        finally:
            await return_db_connection(conn)

        # 检查向量数据库
        vector_status = "healthy" if chroma_collection else "unhealthy"

        return {
            "status": "healthy",
            "components": {
                "database": db_status,
                "vector_database": vector_status
            },
            "timestamp": time.time()
        }
    except Exception as e:
        print(f"[ERROR] 健康检查失败: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }

# 注册路由
app.include_router(chat_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")

# 根路径
@app.get("/")
async def root():
    """根路径"""
    return {"message": "Welcome to AI Chat API"}

if __name__ == "__main__":
    import uvicorn
    # 启动服务器
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)