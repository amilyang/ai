from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from typing import List, Optional
import json
import time

from schemas.chat import ChatRequest, SessionCreate
from errors import streaming_error_response
from database import get_db_connection, return_db_connection
from config import MODEL_CONFIGS, MAX_HISTORY_MESSAGES
from services.model_service import generate_streaming_response, build_messages
from services.knowledge_service import process_images, retrieve_relevant_knowledge, build_context

router = APIRouter()

# 辅助函数：保存用户消息到数据库
async def save_user_message(session_id: int, message: str, images: Optional[List[str]]):
    """保存用户消息到数据库
    
    Args:
        session_id: 会话ID
        message: 用户消息内容
        images: 图片列表
    """
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO messages (session_id, role, content, images) VALUES (?, ?, ?, ?)",
                  (session_id, "user", message, json.dumps(images or [])))
        conn.commit()
    finally:
        await return_db_connection(conn)

# 辅助函数：处理图片并返回错误响应（如果需要）
async def handle_images(images: Optional[List[str]]):
    """处理图片内容并返回错误响应（如果需要）
    
    Args:
        images: 图片列表
    
    Returns:
        tuple: (image_context, error_response)
    """
    image_context, is_valid = process_images(images)
    if not is_valid:
        return None, streaming_error_response("VALIDATION_ERROR", "图片格式无效，请上传有效的图片数据")
    return image_context, None

# 辅助函数：构建聊天上下文
async def build_chat_context(session_id: int, message: str, image_context: list, chroma_collection):
    """构建聊天上下文
    
    Args:
        session_id: 会话ID
        message: 用户消息内容
        image_context: 图片上下文
        chroma_collection: ChromaDB集合
    
    Returns:
        tuple: (context_str, history)
    """
    # 检索相关知识
    relevant_chunks, chunk_sources = retrieve_relevant_knowledge(message, chroma_collection)
    # 构建上下文
    context_str = build_context(relevant_chunks, chunk_sources, image_context)
    # 获取历史对话
    history = await get_history_messages(session_id, MAX_HISTORY_MESSAGES)
    return context_str, history

# 辅助函数：准备模型参数
async def prepare_model_parameters(context_str: str, history: list, message: str, images: Optional[List[str]]):
    """准备模型参数
    
    Args:
        context_str: 上下文字符串
        history: 历史对话
        message: 用户消息内容
        images: 图片列表
    
    Returns:
        tuple: (model_config, payload_messages)
    """
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
async def generate_chat_response(model_config: dict, payload_messages: list, session_id: int):
    """生成流式响应
    
    Args:
        model_config: 模型配置
        payload_messages: 消息负载
        session_id: 会话ID
    
    Returns:
        StreamingResponse: 流式响应
    """
    try:
        # 调用模型生成响应
        streamer = generate_streaming_response(model_config, payload_messages, session_id)
        response = StreamingResponse(streamer, media_type="text/event-stream")
        return response
    except Exception as e:
        # 返回一个错误响应
        return streaming_error_response("MODEL_ERROR", f"创建流式响应失败: {str(e)}")

# 辅助函数：获取历史对话
async def get_history_messages(session_id: int, limit: int = 10):
    """从数据库获取历史对话
    
    Args:
        session_id: 会话ID
        limit: 限制数量
    
    Returns:
        list: 历史对话列表
    """
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT role, content, images FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit)
        )
        messages = c.fetchall()
        # 反转消息顺序，使其按时间正序排列
        messages.reverse()

        # 转换为模型需要的格式
        history = []
        for msg in messages:
            role, content, images_json = msg
            images = json.loads(images_json) if images_json else []
            if images:
                # 多模态格式
                msg_content = [
                    {"text": content}
                ]
                for img in images:
                    msg_content.append({"image": img})
                history.append({"role": role, "content": msg_content})
            else:
                # 纯文本格式
                history.append({"role": role, "content": content})
        return history
    finally:
        await return_db_connection(conn)

from fastapi import Depends
from dependencies import get_chroma_collection

# 聊天接口
@router.post("/chat")
async def chat(req: ChatRequest, chroma_collection=Depends(get_chroma_collection)):
    """处理聊天请求
    
    Args:
        req: 聊天请求
        chroma_collection: ChromaDB集合
    
    Returns:
        StreamingResponse: 流式响应
    """
    # 1. 保存用户消息到数据库
    await save_user_message(req.sessionId, req.message, req.images)

    # 2. 处理图片内容
    image_context, error_response = await handle_images(req.images)
    if error_response:
        return error_response

    # 3. 构建聊天上下文
    context_str, history = await build_chat_context(req.sessionId, req.message, image_context, chroma_collection)

    # 4. 准备模型参数
    model_config, payload_messages = await prepare_model_parameters(context_str, history, req.message, req.images)

    # 5. 生成流式响应
    return await generate_chat_response(model_config, payload_messages, req.sessionId)

# 获取会话历史
@router.get("/sessions/{session_id}/messages")
async def get_session_history(session_id: int):
    """获取会话历史
    
    Args:
        session_id: 会话ID
    
    Returns:
        list: 会话历史
    """
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, role, content, images, created_at FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,)
        )
        messages = c.fetchall()
        result = []
        for msg in messages:
            msg_id, role, content, images_json, created_at = msg
            result.append({
                "id": msg_id,
                "role": role,
                "content": content,
                "images": json.loads(images_json) if images_json else [],
                "created_at": created_at
            })
        return result
    finally:
        await return_db_connection(conn)

# 列出所有会话
@router.get("/sessions")
async def list_sessions():
    """列出所有会话
    
    Returns:
        list: 会话列表
    """
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
        sessions = c.fetchall()
        result = []
        for session in sessions:
            session_id, title, created_at = session
            # 获取会话的第一条消息作为预览
            c.execute(
                "SELECT content FROM messages WHERE session_id = ? ORDER BY created_at LIMIT 1",
                (session_id,)
            )
            first_message = c.fetchone()
            preview = first_message[0] if first_message else ""
            result.append({
                "id": session_id,
                "title": title,
                "created_at": created_at,
                "preview": preview[:50] + "..." if len(preview) > 50 else preview
            })
        return result
    finally:
        await return_db_connection(conn)

# 创建新会话
@router.post("/sessions")
async def create_session(req: SessionCreate):
    """创建新会话
    
    Args:
        req: 会话创建请求
    
    Returns:
        dict: 会话信息
    """
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO sessions (title) VALUES (?)", (req.title,))
        session_id = c.lastrowid
        conn.commit()
        return {
            "id": session_id,
            "title": req.title,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    finally:
        await return_db_connection(conn)

# 删除会话
@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int):
    """删除会话
    
    Args:
        session_id: 会话ID
    
    Returns:
        dict: 操作结果
    """
    conn = await get_db_connection()
    try:
        c = conn.cursor()
        # 先删除会话的所有消息
        c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        # 再删除会话
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        if c.rowcount > 0:
            return {"message": "会话删除成功"}
        else:
            raise HTTPException(status_code=404, detail="会话不存在")
    finally:
        await return_db_connection(conn)

# 删除单条消息
@router.delete("/msg/{message_id}")
async def delete_single_message(message_id: int):
    """删除单条消息
    
    Args:
        message_id: 消息ID
    
    Returns:
        dict: 操作结果
    """
    conn = await get_db_connection()
    try:
        c = conn.cursor()

        # 获取要删除的消息信息
        c.execute("SELECT session_id, role, created_at FROM messages WHERE id = ?", (message_id,))
        message = c.fetchone()

        if not message:
            raise HTTPException(status_code=404, detail="消息不存在")

        # 删除消息
        c.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()

        return {
            "message": "消息删除成功",
            "deleted_message_id": message_id
        }
    finally:
        await return_db_connection(conn)
