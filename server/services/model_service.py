import json
import httpx
from config import API_KEY, MODEL_CONFIGS
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict, Any

async def generate_streaming_response(model_config: dict, payload_messages: list, session_id: int):
    """流式调用模型并返回响应
    
    Args:
        model_config: 模型配置
        payload_messages: 消息负载
        session_id: 会话ID
    
    Yields:
        流式响应数据
    """
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
                                            # 只发送新增的部分，避免重复
                                            if content != previous_content:
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
                from database import get_db_connection, return_db_connection
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

def build_messages(system_prompt: str, history: list, message: str, images: Optional[List[str]]):
    """构建消息，支持多模态
    
    Args:
        system_prompt: 系统提示词
        history: 历史对话
        message: 用户消息
        images: 图片列表
    
    Returns:
        tuple: (payload_messages, selected_model)
    """
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
