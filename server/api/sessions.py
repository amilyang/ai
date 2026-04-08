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
@router.post("/session")
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
@router.get("/session/{session_id}")
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
@router.delete("/session/{session_id}")
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

# 删除消息对
@router.delete("/msg/{message_id}")
async def delete_message_pair(message_id: int):
    """删除消息对（用户消息和对应的AI回复）

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

        session_id, role, created_at = message
        deleted_ids = [message_id]

        if role == "user":
            # 删除用户消息和下一条AI回复
            c.execute(
                "SELECT id FROM messages WHERE session_id = ? AND role = 'assistant' AND created_at > ? ORDER BY created_at LIMIT 1",
                (session_id, created_at)
            )
            assistant_msg = c.fetchone()
            if assistant_msg:
                c.execute("DELETE FROM messages WHERE id = ?", (assistant_msg[0],))
                deleted_ids.append(assistant_msg[0])
        elif role == "assistant":
            # 删除AI回复和上一条用户消息
            c.execute(
                "SELECT id FROM messages WHERE session_id = ? AND role = 'user' AND created_at < ? ORDER BY created_at DESC LIMIT 1",
                (session_id, created_at)
            )
            user_msg = c.fetchone()
            if user_msg:
                c.execute("DELETE FROM messages WHERE id = ?", (user_msg[0],))
                deleted_ids.append(user_msg[0])

        # 删除当前消息
        c.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()

        return {
            "message": "消息对删除成功",
            "deleted_message_ids": deleted_ids
        }
    finally:
        await return_db_connection(conn)

# 删除消息及之后的所有消息
@router.delete("/message/{message_id}")
async def delete_message_and_subsequent(message_id: int):
    """删除消息及之后的所有消息

    Args:
        message_id: 消息ID

    Returns:
        dict: 操作结果
    """
    conn = await get_db_connection()
    try:
        c = conn.cursor()

        # 获取要删除的消息信息
        c.execute("SELECT session_id, created_at FROM messages WHERE id = ?", (message_id,))
        message = c.fetchone()

        if not message:
            raise HTTPException(status_code=404, detail="消息不存在")

        session_id, created_at = message

        # 删除该消息及之后的所有消息
        c.execute("DELETE FROM messages WHERE session_id = ? AND created_at >= ?", (session_id, created_at))
        deleted_count = c.rowcount
        conn.commit()

        return {
            "message": f"删除成功，共删除 {deleted_count} 条消息",
            "deleted_count": deleted_count
        }
    finally:
        await return_db_connection(conn)
