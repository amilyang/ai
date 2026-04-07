import hashlib
from io import BytesIO
import pdfplumber
from docx import Document
from PIL import Image
import pytesseract
import chardet

def process_pdf(file_content):
    """处理PDF文件，提取文本
    
    Args:
        file_content: 文件内容
    
    Returns:
        str: 提取的文本
    """
    text = ""
    try:
        with pdfplumber.open(BytesIO(file_content)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text += f"[第{page_num}页]\n{page_text}\n\n"
        return text
    except Exception as e:
        print(f"[ERROR] PDF处理错误: {e}")
        raise

def process_word(file_content):
    """处理Word文件，提取文本
    
    Args:
        file_content: 文件内容
    
    Returns:
        str: 提取的文本
    """
    text = ""
    try:
        doc = Document(BytesIO(file_content))
        for para in doc.paragraphs:
            if para.text:
                text += para.text + "\n"
        return text
    except Exception as e:
        print(f"[ERROR] Word处理错误: {e}")
        raise

def process_image(file_content):
    """处理图片文件，使用OCR提取文本
    
    Args:
        file_content: 文件内容
    
    Returns:
        str: 提取的文本
    """
    text = ""
    try:
        img = Image.open(BytesIO(file_content))
        text = pytesseract.image_to_string(img, lang='chi_sim+eng')
        return text
    except Exception as e:
        print(f"[ERROR] 图片处理错误: {e}")
        raise

def calculate_file_hash(content):
    """计算文件哈希值，用于重复检测
    
    Args:
        content: 文件内容
    
    Returns:
        str: 文件哈希值
    """
    return hashlib.md5(content).hexdigest()

def generate_file_summary(text, max_length=200):
    """生成文件摘要
    
    Args:
        text: 文件文本
        max_length: 摘要最大长度
    
    Returns:
        str: 文件摘要
    """
    # 简单的摘要生成：取前max_length个字符
    summary = text.strip()
    if len(summary) > max_length:
        summary = summary[:max_length] + "..."
    return summary

def check_file_security(text):
    """文件内容安全检查
    
    Args:
        text: 文件文本
    
    Returns:
        tuple: (is_safe, message)
    """
    # 更智能的安全检查，区分恶意代码和合法内容
    # 只检查可能导致安全问题的具体模式
    unsafe_patterns = [
        # 危险的JavaScript执行
        "eval(", "exec(", "system(",
        # 危险的SQL操作
        "DROP TABLE", "DELETE FROM", "INSERT INTO"
    ]

    text_lower = text.lower()
    for pattern in unsafe_patterns:
        if pattern.lower() in text_lower:
            return False, f"文件包含不安全内容: {pattern}"

    # 检查文件长度
    if len(text) > 1000000:  # 1MB
        return False, "文件内容过长"

    return True, "文件内容安全"
