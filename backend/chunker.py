def chunk_text(text: str, size: int = 1000, overlap: int = 200) -> list[str]:
    text = text.strip()
    chunks = []
    start = 0

    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap

    return chunks