import pdfplumber

def extract_text_from_pdf(file_path: str) -> str:
    full_text = ""
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                # 加上页码标记，方便 AI 理解上下文来源
                full_text += f"\n--- [第 {i+1} 页] ---\n{text}\n"
    return full_text