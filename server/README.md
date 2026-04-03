# 启动命令

<br />

netstat -ano | findstr :8000

taskkill /PID 25480 /F

python -m uvicorn main:app --host 0.0.0.0 --port 8000
