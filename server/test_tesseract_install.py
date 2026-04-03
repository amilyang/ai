'''
Author: e0042176 e0042176@ceic.com
Date: 2026-04-02 14:00:35
LastEditors: e0042176 e0042176@ceic.com
LastEditTime: 2026-04-02 14:23:46
FilePath: \ai\server\test_tesseract_install.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
import os
import subprocess
import sys

print("Testing tesseract installation...")
print(f"Python version: {sys.version}")
print(f"Current working directory: {os.getcwd()}")
print(f"System PATH: {os.environ.get('PATH', '')}")

# 检查tesseract是否在PATH中
tesseract_path = None
try:
    # 尝试运行tesseract命令
    result = subprocess.run(['tesseract', '--version'], capture_output=True, text=True, timeout=5)
    print(f"tesseract --version output:\n{result.stdout}")
    print(f"tesseract --version error:\n{result.stderr}")
    print(f"tesseract --version return code: {result.returncode}")
    tesseract_path = "Found in PATH"
except Exception as e:
    print(f"Error running tesseract: {e}")

# 检查常见的tesseract安装路径
common_paths = [
    "C:\Program Files\Tesseract-OCR\tesseract.exe",
    "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "D:\Program Files\Tesseract-OCR\tesseract.exe",
    "D:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
]

for path in common_paths:
    if os.path.exists(path):
        print(f"Found tesseract at: {path}")
        tesseract_path = path
        break

if tesseract_path:
    print("tesseract is installed!")
    # 尝试设置环境变量
    os.environ['TESSERACT_CMD'] = tesseract_path
    print(f"Set TESSERACT_CMD to: {tesseract_path}")

    # 尝试导入pytesseract并测试
    try:
        import pytesseract
        print(f"pytesseract version: {pytesseract.get_tesseract_version()}")
        print("pytesseract is working!")
    except Exception as e:
        print(f"Error with pytesseract: {e}")
else:
    print("tesseract is not installed or not in PATH.")

print("Test completed.")
