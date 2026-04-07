from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import json

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

# 全局异常处理函数
def setup_exception_handlers(app):
    """设置全局异常处理"""
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
