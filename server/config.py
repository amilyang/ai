import os
import dotenv

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

# 服务器配置
PORT = int(os.getenv("PORT", 8000))  # 服务器端口

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

# 验证API密钥
if not API_KEY:
    raise ValueError("错误: 请在 .env 文件中设置 DASHSCOPE_API_KEY")
