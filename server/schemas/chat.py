from pydantic import BaseModel, field_validator
from typing import List, Optional

class ChatRequest(BaseModel):
    """聊天请求模型"""
    sessionId: int
    message: str = ""
    images: Optional[List[str]] = None
    
    # 输入验证
    @field_validator('sessionId')
    @classmethod
    def session_id_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('会话ID必须为正数')
        return v
    
    @field_validator('message')
    @classmethod
    def message_length_check(cls, v):
        if len(v) > 10000:
            raise ValueError('消息长度不能超过10000字符')
        return v
    
    @field_validator('images')
    @classmethod
    def images_length_check(cls, v):
        if v and len(v) > 5:
            raise ValueError('图片数量不能超过5张')
        return v

class SessionCreate(BaseModel):
    """会话创建模型"""
    title: Optional[str] = "新对话"
    
    @field_validator('title')
    @classmethod
    def title_length_check(cls, v):
        if v and len(v) > 100:
            raise ValueError('会话标题长度不能超过100字符')
        return v
