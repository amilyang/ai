import sqlite3
import threading
from queue import Queue

# 数据库初始化 (SQLite)
def init_sqlite(db_path):
    """初始化SQLite数据库"""
    conn = sqlite3.connect(db_path) # 连接数据库（没有就创建）
    c = conn.cursor() # 获取"指针"，用来执行 SQL 命令
    # 创建 sessions 表（存储对话会话）
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT DEFAULT '新对话',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 创建 messages 表（存储消息）
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            images TEXT DEFAULT '[]',  -- 存储图片 URL 列表的 JSON 字符串
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
    ''')
    conn.commit() # 提交保存
    conn.close() # 关闭连接
    print(f"[DB] SQLite 数据库已初始化: {db_path}")

# 向量数据库初始化 (ChromaDB)
def init_chroma(chroma_persist_dir):
    """初始化ChromaDB向量数据库"""
    import chromadb
    client = chromadb.PersistentClient(path=chroma_persist_dir) # 创建持久化客户端
    collection = client.get_or_create_collection(name="knowledge_base") # 获取/创建集合
    print(f"[DB] ChromaDB 向量库已初始化: {chroma_persist_dir}")
    return collection

# 数据库连接池
class SQLiteConnectionPool:
    def __init__(self, db_path, max_connections=5):
        """初始化数据库连接池"""
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool = Queue(maxsize=max_connections)
        self.lock = threading.Lock()
        
        # 初始化连接池
        for _ in range(max_connections):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            self.pool.put(conn)
    
    def get_connection(self):
        """从连接池获取连接"""
        return self.pool.get()
    
    def return_connection(self, conn):
        """将连接归还到连接池"""
        if conn:
            self.pool.put(conn)
    
    def close_all(self):
        """关闭所有连接"""
        while not self.pool.empty():
            try:
                conn = self.pool.get_nowait()
                conn.close()
            except:
                pass

# 全局连接池实例
db_pool = None

def init_db_pool(db_path, max_connections=5):
    """初始化数据库连接池"""
    global db_pool
    db_pool = SQLiteConnectionPool(db_path, max_connections)

async def get_db_connection():
    """从连接池获取数据库连接"""
    if not db_pool:
        from config import DB_PATH
        init_db_pool(DB_PATH)
    return db_pool.get_connection()

async def return_db_connection(conn):
    """归还数据库连接到连接池"""
    if db_pool and conn:
        db_pool.return_connection(conn)
