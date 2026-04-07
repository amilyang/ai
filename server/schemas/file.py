from pydantic import BaseModel

class FileResponse(BaseModel):
    """文件上传响应模型"""
    message: str
    filename: str
    success: bool
    duplicate: bool = False
    processed_chunks: int = 0
    total_chunks: int = 0
    processing_time: str = ""

class FileListResponse(BaseModel):
    """文件列表响应模型"""
    files: list
    total: int
