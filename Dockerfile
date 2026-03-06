FROM python:3.9-slim

WORKDIR /app

# 复制依赖文件
COPY server/requirements.txt .
# 如果没有 requirements.txt，先手动创建一个，内容如下：
# fastapi
# uvicorn
# aiosqlite
# python-dotenv
# httpx

RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server ./server

WORKDIR /app/server

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]