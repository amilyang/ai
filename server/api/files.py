from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import List
import os

from schemas.file import FileResponse, FileListResponse
from services.file_service import process_uploaded_file

router = APIRouter()

from fastapi import Depends
from dependencies import get_chroma_collection

# 上传文件接口
@router.post("/files", response_model=FileResponse)
async def upload_file(file: UploadFile = File(...), chroma_collection=Depends(get_chroma_collection)):
    """上传文件并构建向量索引
    
    Args:
        file: 上传的文件
        chroma_collection: ChromaDB集合
    
    Returns:
        FileResponse: 文件上传结果
    """
    try:
        # 读取文件内容
        content = await file.read()
        # 处理文件
        result = await process_uploaded_file(content, file.filename, chroma_collection)
        # 检查是否成功
        if not result.get("success", False):
            raise HTTPException(status_code=400, detail=result.get("message", "文件上传失败"))
        # 返回成功响应
        return FileResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传文件时发生错误: {str(e)}")

# 列出已上传的文件
@router.get("/files", response_model=FileListResponse)
async def list_files(chroma_collection=Depends(get_chroma_collection)):
    """列出已上传的文件
    
    Args:
        chroma_collection: ChromaDB集合
    
    Returns:
        FileListResponse: 文件列表
    """
    try:
        if not chroma_collection:
            return FileListResponse(files=[], total=0)
        
        # 从 ChromaDB 获取所有文档的元数据
        result = chroma_collection.get(include=["metadatas"])
        if not result or not result.get("metadatas"):
            return FileListResponse(files=[], total=0)
        
        # 提取唯一的文件信息
        files = []
        seen_files = set()
        
        for metadata in result["metadatas"]:
            if metadata and "source" in metadata and metadata["source"] not in seen_files:
                file_info = {
                    "filename": metadata["source"],
                    "file_size": metadata.get("file_size", 0),
                    "file_summary": metadata.get("file_summary", ""),
                    "timestamp": metadata.get("timestamp", 0)
                }
                files.append(file_info)
                seen_files.add(metadata["source"])
        
        return FileListResponse(files=files, total=len(files))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文件列表时发生错误: {str(e)}")
