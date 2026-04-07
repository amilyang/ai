from fastapi import APIRouter, HTTPException
import time
import json

from schemas.chat import SessionCreate
from database import get_db_connection, return_db_connection

router = APIRouter()

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
