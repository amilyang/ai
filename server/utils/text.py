from config import CHUNK_SIZE, CHUNK_OVERLAP

def chunk_text(text: str, chunk_size: int = None, overlap: int = None):
    """智能文本分块逻辑，基于段落和句子分块
    
    Args:
        text: 要分块的文本
        chunk_size: 块大小
        overlap: 重叠大小
    
    Returns:
        list: 分块后的文本列表
    """
    # 使用配置值作为默认值
    if chunk_size is None:
        chunk_size = CHUNK_SIZE
    if overlap is None:
        overlap = CHUNK_OVERLAP

    chunks = []

    # 首先按段落分割
    paragraphs = text.split('\n\n')
    current_chunk = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        # 如果当前段落本身就小于chunk_size，直接添加到当前块
        if len(current_chunk) + len(paragraph) + 2 <= chunk_size:
            if current_chunk:
                current_chunk += '\n\n' + paragraph
            else:
                current_chunk = paragraph
        else:
            # 如果当前块不为空，先保存
            if current_chunk:
                chunks.append(current_chunk)
                # 计算重叠部分
                overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                current_chunk = overlap_text

            # 处理长段落，按句子分割
            sentences = []
            # 简单的句子分割（实际应用中可能需要更复杂的NLP处理）
            temp_sentence = ""
            for char in paragraph:
                temp_sentence += char
                if char in ['.', '。', '!', '！', '?', '？', ';', '；']:
                    sentences.append(temp_sentence)
                    temp_sentence = ""
            if temp_sentence:
                sentences.append(temp_sentence)

            # 组合句子到块中
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 <= chunk_size:
                    if current_chunk:
                        current_chunk += ' ' + sentence
                    else:
                        current_chunk = sentence
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                        overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                        current_chunk = overlap_text + ' ' + sentence
                    else:
                        # 单个句子就超过chunk_size，强制分割
                        start_idx = 0
                        while start_idx < len(sentence):
                            end_idx = start_idx + chunk_size
                            chunks.append(sentence[start_idx:end_idx])
                            start_idx += chunk_size - overlap
                        current_chunk = ""

    # 保存最后一个块
    if current_chunk:
        chunks.append(current_chunk)

    return chunks
